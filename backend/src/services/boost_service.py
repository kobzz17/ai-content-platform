"""Boost service — all bot accounts comment on a Telegram channel post."""
import asyncio
import logging
import random
from datetime import datetime
from sqlalchemy import select, desc
from src.database import async_session_maker
from src.models import BoostTask, BoostLog, BoostStatus, BotTask, TaskStatus, Account
import src.session_manager as sm

logger = logging.getLogger(__name__)

_running: dict[int, asyncio.Task] = {}


async def start_boost(boost_id: int) -> None:
    if boost_id in _running:
        return
    t = asyncio.create_task(_boost_campaign(boost_id), name=f"boost-{boost_id}")
    _running[boost_id] = t
    t.add_done_callback(lambda _: _running.pop(boost_id, None))
    logger.info("Started boost campaign %d", boost_id)


async def stop_boost(boost_id: int) -> None:
    t = _running.pop(boost_id, None)
    if t and not t.done():
        t.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(t), timeout=3.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass


async def start_all_running() -> None:
    async with async_session_maker() as db:
        r = await db.execute(
            select(BoostTask).where(BoostTask.status == BoostStatus.running)
        )
        boosts = r.scalars().all()
    for b in boosts:
        await start_boost(b.id)
    if boosts:
        logger.info("Resumed %d boost campaign(s) from DB", len(boosts))


async def _find_disc_thread(
    client, channel_entity, message_id: int, post_date=None
) -> tuple[object | None, int | None, list[str]]:
    """Find the discussion thread for a channel post.

    Returns (disc_group_entity, linked_msg_id, existing_comments).
    Returns (None, None, []) if no thread exists.
    """
    from datetime import timedelta
    from telethon.tl.functions.messages import GetDiscussionMessageRequest
    from telethon.tl.functions.channels import GetFullChannelRequest, JoinChannelRequest

    existing: list[str] = []

    # Method 1: standard API (posts with replies.comments=True)
    try:
        disc = await client(GetDiscussionMessageRequest(peer=channel_entity, msg_id=message_id))
        if disc.chats and disc.messages:
            disc_msg_id = disc.messages[0].id
            disc_group = await client.get_entity(disc.chats[0])
            async for cmsg in client.iter_messages(disc_group, reply_to=disc_msg_id, limit=15):
                txt = getattr(cmsg, "message", None) or ""
                if txt.strip():
                    existing.append(txt[:200])
            logger.info("_find_disc_thread: method1 OK linked_msg=%d", disc_msg_id)
            return disc_group, disc_msg_id, existing
    except Exception as e:
        logger.info("_find_disc_thread: method1 failed (%s), trying fwd search", e)

    # Method 2: manual fwd_from search near post_date
    full = await client(GetFullChannelRequest(channel_entity))
    linked_chat_id = full.full_chat.linked_chat_id
    if not linked_chat_id:
        logger.warning("_find_disc_thread: channel has no linked discussion group")
        return None, None, []

    disc_chat_raw = next((c for c in full.chats if c.id == linked_chat_id), None)
    if not disc_chat_raw:
        logger.warning("_find_disc_thread: linked chat %d not in full.chats", linked_chat_id)
        return None, None, []

    try:
        await client(JoinChannelRequest(disc_chat_raw))
    except Exception as e:
        logger.info("_find_disc_thread: join disc group: %s", e)

    # Use the Chat object returned by GetFullChannelRequest — it already has access_hash
    disc_entity = await client.get_entity(disc_chat_raw)
    logger.info("_find_disc_thread: disc_entity resolved id=%d", disc_entity.id)

    channel_id = channel_entity.id
    if post_date:
        search_kwargs: dict = {"offset_date": post_date + timedelta(minutes=5), "limit": 20}
    else:
        search_kwargs = {"limit": 300}

    async for fwd_msg in client.iter_messages(disc_entity, **search_kwargs):
        fwd = getattr(fwd_msg, "fwd_from", None)
        if not fwd:
            continue
        fwd_ch = getattr(fwd, "from_id", None)
        if (
            getattr(fwd_ch, "channel_id", None) == channel_id
            and getattr(fwd, "channel_post", None) == message_id
        ):
            try:
                async for cmsg in client.iter_messages(disc_entity, reply_to=fwd_msg.id, limit=15):
                    txt = getattr(cmsg, "message", None) or ""
                    if txt.strip():
                        existing.append(txt[:200])
            except Exception as e:
                logger.info("_find_disc_thread: skipping existing comment read: %s", e)
            logger.info("_find_disc_thread: method2 OK linked_msg=%d existing=%d",
                        fwd_msg.id, len(existing))
            return disc_entity, fwd_msg.id, existing

    logger.warning("_find_disc_thread: linked message for msg %d not found in disc group", message_id)
    return None, None, []


async def _boost_campaign(boost_id: int) -> None:
    from src.services.ai_service import analyze_post_for_boost

    async with async_session_maker() as db:
        boost = await db.get(BoostTask, boost_id)
        if not boost:
            return
        channel_peer = boost.channel_peer
        message_id = boost.message_id
        topic = boost.topic
        duration_min = boost.duration_minutes

    # Get all running bot tasks (deduplicated by account)
    async with async_session_maker() as db:
        r = await db.execute(
            select(BotTask).where(BotTask.status == TaskStatus.running)
        )
        all_tasks = r.scalars().all()

    seen: set[int] = set()
    bot_tasks: list[BotTask] = []
    for bt in all_tasks:
        if bt.account_id not in seen:
            seen.add(bt.account_id)
            bot_tasks.append(bt)

    if not bot_tasks:
        logger.warning("Boost %d: no running bot tasks found", boost_id)
        async with async_session_maker() as db:
            b = await db.get(BoostTask, boost_id)
            if b:
                b.status = BoostStatus.done
                await db.commit()
        return

    # Fetch post text, media and find discussion thread
    post_text = ""
    post_media_bytes: bytes | None = None
    post_media_type: str = "image/jpeg"
    disc_group_entity = None
    disc_linked_msg_id: int | None = None
    real_existing_comments: list[str] = []
    fetch_error: str | None = None

    if channel_peer:
        fetch_errors: list[str] = []
        for bt in bot_tasks:  # try ALL accounts until one succeeds
            try:
                async with async_session_maker() as db:
                    acc = await db.get(Account, bt.account_id)
                client = await sm.get_client(acc.id, acc.session_string, acc.proxy)
                channel_entity = await client.get_entity(channel_peer)
                try:
                    from telethon.tl.functions.channels import JoinChannelRequest
                    await client(JoinChannelRequest(channel_entity))
                except Exception:
                    pass

                msg = None
                async for m in client.iter_messages(channel_entity, ids=[message_id]):
                    msg = m
                    break
                if msg is None:
                    msg = await client.get_messages(channel_entity, ids=message_id)

                if msg:
                    text = (getattr(msg, "message", None) or "").strip()
                    if text:
                        post_text = text[:600]
                    # Download photo or video thumbnail for visual context
                    if post_media_bytes is None:
                        try:
                            if getattr(msg, "photo", None):
                                post_media_bytes = await client.download_media(msg.photo, bytes)
                                post_media_type = "image/jpeg"
                                logger.info("Boost %d: downloaded photo (%d bytes)",
                                            boost_id, len(post_media_bytes))
                            elif getattr(msg, "document", None):
                                doc = msg.document
                                thumbs = getattr(doc, "thumbs", None) or []
                                if thumbs:
                                    post_media_bytes = await client.download_media(
                                        doc.thumbs[-1], bytes
                                    )
                                    post_media_type = "image/jpeg"
                                    logger.info("Boost %d: downloaded video thumb (%d bytes)",
                                                boost_id, len(post_media_bytes))
                        except Exception as e:
                            logger.info("Boost %d: media download skipped: %s", boost_id, e)
                else:
                    fetch_errors.append(f"acc {bt.account_id}: message not found")
                    continue
            except Exception as e:
                fetch_errors.append(f"acc {bt.account_id}: {e}")
                logger.warning("Boost %d: fetch failed via acc %d: %s", boost_id, bt.account_id, e)
                continue

            # Run _find_disc_thread outside the fetch try/except so its errors are visible
            try:
                disc_group_entity, disc_linked_msg_id, real_existing_comments = (
                    await _find_disc_thread(client, channel_entity, message_id,
                                            post_date=getattr(msg, "date", None))
                )
            except Exception as e:
                logger.warning("Boost %d: _find_disc_thread failed via acc %d: %s",
                               boost_id, bt.account_id, e)
                continue  # try next account

            if disc_group_entity is not None:
                logger.info(
                    "Boost %d: post %d chars, disc_thread=%s, existing=%d from %s",
                    boost_id, len(post_text),
                    disc_linked_msg_id, len(real_existing_comments), channel_peer,
                )
                break  # found thread — stop trying more accounts
            # else: thread not found via this account, try next one

        if disc_group_entity is None:
            if fetch_errors and not post_text:
                fetch_error = (
                    f"Нет доступа к посту {channel_peer}/{message_id}. "
                    f"Детали: {'; '.join(fetch_errors[:2])}"
                )
            else:
                fetch_error = (
                    f"Пост {channel_peer}/{message_id} не имеет треда обсуждений. "
                    f"Возможно, канал не связан с группой или пост слишком старый."
                )

    if fetch_error:
        logger.error("Boost %d: %s", boost_id, fetch_error)
        async with async_session_maker() as db:
            db.add(BoostLog(boost_id=boost_id, account_id=bot_tasks[0].account_id,
                            action="error", text=fetch_error))
            b = await db.get(BoostTask, boost_id)
            if b:
                b.status = BoostStatus.done
            await db.commit()
        return

    # Auto-generate discussion topic from post content if not provided
    if not topic:
        if post_text:
            try:
                topic = await analyze_post_for_boost(post_text)
                async with async_session_maker() as db:
                    b = await db.get(BoostTask, boost_id)
                    if b:
                        b.topic = topic
                        await db.commit()
                logger.info("Boost %d: auto topic = %s", boost_id, topic[:60])
            except Exception as e:
                logger.warning("Boost %d: topic analysis failed: %s", boost_id, e)
        topic = topic or "обсуждение поста"

    # Search web for extra context about people/events in the post (once, shared by all bots)
    extra_context = ""
    if post_text:
        try:
            from src.services.ai_service import search_boost_context
            extra_context = await search_boost_context(post_text)
            if extra_context:
                logger.info("Boost %d: web context fetched (%d chars)", boost_id, len(extra_context))
        except Exception as e:
            logger.warning("Boost %d: web context search failed: %s", boost_id, e)

    async with async_session_maker() as db:
        b = await db.get(BoostTask, boost_id)
        if b:
            b.total_accounts = len(bot_tasks)
            await db.commit()

    random.shuffle(bot_tasks)
    n = len(bot_tasks)
    slot_min = duration_min / n if n > 0 else duration_min

    # Pre-assign comment formats and opinion stances for guaranteed diversity
    from src.services.ai_service import _COMMENT_FORMATS, _STANCE_INSTRUCTIONS
    fmt_pool = list(_COMMENT_FORMATS)  # list of (name, instruction)
    stance_pool = list(_STANCE_INSTRUCTIONS.keys())
    # Repeat pools to cover all bots, then shuffle
    assigned_formats = (fmt_pool * ((n // len(fmt_pool)) + 1))[:n]
    assigned_stances = (stance_pool * ((n // len(stance_pool)) + 1))[:n]
    random.shuffle(assigned_formats)
    random.shuffle(assigned_stances)

    # Load style memory (past comments) per account from BoostLog
    style_memory: dict[int, list[str]] = {}
    async with async_session_maker() as db:
        for bt in bot_tasks:
            r = await db.execute(
                select(BoostLog.text)
                .where(BoostLog.account_id == bt.account_id)
                .where(BoostLog.action == "commented")
                .order_by(desc(BoostLog.id))
                .limit(8)
            )
            rows = r.fetchall()
            style_memory[bt.account_id] = [row[0] for row in rows if row[0]]

    # Shared list of posted comments with msg_id so later bots can reply to earlier ones
    posted_comments: list[dict] = []

    sub_tasks = []
    for i, bt in enumerate(bot_tasks):
        jitter = random.uniform(-min(2.0, slot_min / 4), min(2.0, slot_min / 4))
        delay_sec = max(15.0, (i * slot_min + jitter) * 60)
        sub_tasks.append(asyncio.create_task(
            _post_comment(
                delay_sec, boost_id, channel_peer, message_id,
                bt.account_id, bt.persona, post_text, topic, posted_comments,
                real_existing_comments, i,
                disc_group_entity, disc_linked_msg_id,
                extra_context=extra_context,
                media_bytes=post_media_bytes,
                media_type=post_media_type,
                assigned_format=assigned_formats[i],
                stance=assigned_stances[i],
                style_examples=style_memory.get(bt.account_id, []),
            )
        ))

    await asyncio.gather(*sub_tasks, return_exceptions=True)

    # Phase 2: continuation replies + emoji reactions
    if len(posted_comments) >= 2:
        await asyncio.gather(
            _continuation_phase(
                boost_id, posted_comments, bot_tasks,
                disc_group_entity, disc_linked_msg_id,
                post_text, style_memory, channel_peer,
            ),
            _add_reactions(boost_id, posted_comments, bot_tasks, disc_group_entity),
            return_exceptions=True,
        )

    async with async_session_maker() as db:
        b = await db.get(BoostTask, boost_id)
        if b and b.status == BoostStatus.running:
            b.status = BoostStatus.done
            await db.commit()

    logger.info("Boost %d done — %d accounts, %d comments", boost_id, n, len(posted_comments))


async def _continuation_phase(
    boost_id: int,
    posted_comments: list[dict],
    bot_tasks: list,
    disc_group_entity,
    disc_linked_msg_id: int | None,
    post_text: str,
    style_memory: dict[int, list[str]],
    channel_peer: str | None = None,
) -> None:
    """2-3 bots come back and continue the discussion with replies to each other."""
    from src.services.ai_service import generate_continuation_comment
    from telethon.tl.functions.channels import JoinChannelRequest

    # Wait before continuation (5-12 minutes after last initial comment)
    await asyncio.sleep(random.uniform(300, 720))

    async with async_session_maker() as db:
        b = await db.get(BoostTask, boost_id)
        if not b or b.status != BoostStatus.running:
            return

    # Pick 2-3 bots for continuation (prefer bots with opposing stances)
    eligible = [bt for bt in bot_tasks if any(c["account_id"] == bt.account_id for c in posted_comments)]
    n_cont = min(random.randint(2, 3), len(eligible))
    participants = random.sample(eligible, n_cont)

    for bt in participants:
        # Each participant waits a bit between each other
        await asyncio.sleep(random.uniform(60, 180))

        async with async_session_maker() as db:
            b = await db.get(BoostTask, boost_id)
            if not b or b.status != BoostStatus.running:
                break
            acc = await db.get(Account, bt.account_id)
        if not acc:
            continue

        # Find my stance from my initial comment
        my_entry = next((c for c in posted_comments if c["account_id"] == bt.account_id), None)
        own_stance = my_entry.get("stance", "neutral") if my_entry else "neutral"

        # Pick a target comment from someone else
        targets = [c for c in posted_comments if c["account_id"] != bt.account_id and c.get("msg_id")]
        if not targets:
            continue

        # Prefer opposite stances for drama, same stance for agreement
        opposite = {"positive": "critical", "critical": "positive"}
        preferred = [t for t in targets if t.get("stance") == opposite.get(own_stance)]
        target = random.choice(preferred) if preferred and random.random() < 0.6 else random.choice(targets)

        try:
            client = await sm.get_client(acc.id, acc.session_string, acc.proxy)
            comment = await generate_continuation_comment(
                post_text=post_text,
                persona=bt.persona,
                own_stance=own_stance,
                target_comment=target["text"],
                target_stance=target.get("stance", "neutral"),
                all_comments=[c["text"] for c in posted_comments],
                style_examples=style_memory.get(bt.account_id, []),
            )

            if disc_group_entity is not None and disc_linked_msg_id is not None:
                disc_group_id = disc_group_entity.id
                try:
                    await client(JoinChannelRequest(disc_group_entity))
                except Exception:
                    pass
                try:
                    my_disc = await client.get_entity(int(f"-100{disc_group_id}"))
                except Exception:
                    my_disc = disc_group_entity
                sent = await client.send_message(my_disc, comment, reply_to=target["msg_id"])
            else:
                # No discussion group — reply directly to the channel post
                ch_entity = await client.get_entity(channel_peer if channel_peer else disc_linked_msg_id)
                sent = await client.send_message(ch_entity, comment, comment_to=disc_linked_msg_id)

            sent_id = sent.id if sent else None
            posted_comments.append({
                "text": comment,
                "msg_id": sent_id,
                "account_id": bt.account_id,
                "persona": bt.persona[:80],
                "stance": own_stance,
            })

            async with async_session_maker() as db:
                db.add(BoostLog(boost_id=boost_id, account_id=bt.account_id,
                                action="commented", text=comment))
                b = await db.get(BoostTask, boost_id)
                if b:
                    b.comments_posted += 1
                await db.commit()

            logger.info("Boost %d: acc %d continuation reply (stance=%s→%s)",
                        boost_id, bt.account_id, own_stance, target.get("stance", "?"))

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("Boost %d: continuation reply failed acc %d: %s", boost_id, bt.account_id, e)


_REACTION_EMOJIS = ["❤", "👍", "🔥", "😂", "👏", "😮", "🤔", "💀", "🫡", "❤‍🔥"]


async def _add_reactions(
    boost_id: int,
    posted_comments: list[dict],
    bot_tasks: list,
    disc_group_entity,
) -> None:
    """Some bots randomly react to each other's comments."""
    from telethon.tl.functions.messages import SendReactionRequest
    from telethon.tl.functions.channels import JoinChannelRequest
    from telethon.tl.types import ReactionEmoji

    if disc_group_entity is None:
        return

    # Wait until a few initial comments are up
    await asyncio.sleep(random.uniform(120, 300))

    async with async_session_maker() as db:
        b = await db.get(BoostTask, boost_id)
        if not b or b.status != BoostStatus.running:
            return

    disc_group_id = disc_group_entity.id
    # ~60% of bots add 1-2 reactions
    reactors = [bt for bt in bot_tasks if random.random() < 0.6]

    for bt in reactors:
        await asyncio.sleep(random.uniform(30, 90))
        targets = [c for c in posted_comments
                   if c["account_id"] != bt.account_id and c.get("msg_id")]
        if not targets:
            continue
        # React to 1-2 comments
        to_react = random.sample(targets, min(random.randint(1, 2), len(targets)))
        try:
            async with async_session_maker() as db:
                acc = await db.get(Account, bt.account_id)
            if not acc:
                continue
            client = await sm.get_client(acc.id, acc.session_string, acc.proxy)
            try:
                await client(JoinChannelRequest(disc_group_entity))
            except Exception:
                pass
            try:
                my_disc = await client.get_entity(int(f"-100{disc_group_id}"))
            except Exception:
                my_disc = disc_group_entity

            for target in to_react:
                emoji = random.choice(_REACTION_EMOJIS)
                try:
                    await client(SendReactionRequest(
                        peer=my_disc,
                        msg_id=target["msg_id"],
                        reaction=[ReactionEmoji(emoticon=emoji)],
                    ))
                    logger.info("Boost %d: acc %d reacted %s to msg %d",
                                boost_id, bt.account_id, emoji, target["msg_id"])
                    await asyncio.sleep(random.uniform(5, 20))
                except Exception as e:
                    logger.info("Boost %d: reaction skipped: %s", boost_id, e)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("Boost %d: reactions failed acc %d: %s", boost_id, bt.account_id, e)


async def _post_comment(
    delay_sec: float,
    boost_id: int,
    channel_peer: str | None,
    message_id: int,
    account_id: int,
    persona: str,
    post_text: str,
    topic: str,
    posted_comments: list[dict],
    real_comments: list[str] | None = None,
    style_index: int = 0,
    disc_group_entity=None,
    disc_linked_msg_id: int | None = None,
    extra_context: str = "",
    media_bytes: bytes | None = None,
    media_type: str = "image/jpeg",
    assigned_format: tuple[str, str] | None = None,
    stance: str = "neutral",
    style_examples: list[str] | None = None,
) -> None:
    from src.services.ai_service import generate_boost_comment

    await asyncio.sleep(delay_sec)

    async with async_session_maker() as db:
        b = await db.get(BoostTask, boost_id)
        if not b or b.status != BoostStatus.running:
            return

    async with async_session_maker() as db:
        acc = await db.get(Account, account_id)
    if not acc:
        return

    try:
        client = await sm.get_client(acc.id, acc.session_string, acc.proxy)

        own_texts = [c["text"] for c in posted_comments if c.get("account_id") == account_id]
        comment, reply_to_index = await generate_boost_comment(
            post_text, topic, persona,
            own_comments=own_texts,
            real_comments=real_comments,
            style_index=style_index,
            prev_comments=list(posted_comments),
            extra_context=extra_context,
            media_bytes=media_bytes,
            media_type=media_type,
            assigned_format=assigned_format,
            stance=stance,
            style_examples=style_examples,
        )

        # Determine which message to reply to
        reply_to_id = disc_linked_msg_id
        if reply_to_index is not None and 0 <= reply_to_index < len(posted_comments):
            prev_msg_id = posted_comments[reply_to_index].get("msg_id")
            if prev_msg_id:
                reply_to_id = prev_msg_id

        sent = None
        if channel_peer:
            from telethon.tl.functions.channels import JoinChannelRequest

            if disc_group_entity is not None and disc_linked_msg_id is not None:
                # disc_group_entity access_hash is per-account; re-resolve for this client.
                disc_group_id = disc_group_entity.id
                try:
                    await client(JoinChannelRequest(disc_group_entity))
                except Exception:
                    pass
                try:
                    my_disc = await client.get_entity(int(f"-100{disc_group_id}"))
                except Exception:
                    my_disc = disc_group_entity
                sent = await client.send_message(my_disc, comment, reply_to=reply_to_id)
            else:
                channel_entity = await client.get_entity(channel_peer)
                try:
                    await client(JoinChannelRequest(channel_entity))
                except Exception:
                    pass
                sent = await client.send_message(channel_entity, comment, comment_to=message_id)
        else:
            sent = await client.send_message(message_id, comment)

        sent_id = sent.id if sent else None
        posted_comments.append({
            "text": comment,
            "msg_id": sent_id,
            "account_id": account_id,
            "persona": persona[:80],
            "stance": stance,
        })

        async with async_session_maker() as db:
            db.add(BoostLog(boost_id=boost_id, account_id=account_id,
                            action="commented", text=comment))
            b = await db.get(BoostTask, boost_id)
            if b:
                b.comments_posted += 1
            await db.commit()

        logger.info("Boost %d: acc %d commented on %s msg %d",
                    boost_id, account_id, channel_peer, message_id)

    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error("Boost %d: acc %d failed: %s", boost_id, account_id, e)
        try:
            async with async_session_maker() as db:
                db.add(BoostLog(boost_id=boost_id, account_id=account_id,
                                action="error", text=str(e)[:300]))
                await db.commit()
        except Exception:
            pass
