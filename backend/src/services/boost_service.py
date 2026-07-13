"""Boost service — all bot accounts comment on a Telegram channel post."""
import asyncio
import logging
import random
from datetime import datetime
from sqlalchemy import select
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


async def _boost_campaign(boost_id: int) -> None:
    from src.services.ai_service import analyze_post_for_boost

    async with async_session_maker() as db:
        boost = await db.get(BoostTask, boost_id)
        if not boost:
            return
        channel_peer = boost.channel_peer  # e.g. "@channelname" or "-100123456"
        message_id = boost.message_id
        topic = boost.topic
        duration_min = boost.duration_minutes

    # Get all running bot tasks (deduplicated by account)
    async with async_session_maker() as db:
        r = await db.execute(
            select(BotTask).where(BotTask.status == TaskStatus.running)
        )
        all_tasks = r.scalars().all()

    # Deduplicate: one task per account (take the first one found)
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

    # Fetch the channel post text and verify comments are enabled
    post_text = ""
    comments_enabled = False
    real_existing_comments: list[str] = []
    _working_client = None
    _working_entity = None
    if channel_peer:
        for bt in bot_tasks[:3]:
            try:
                async with async_session_maker() as db:
                    acc = await db.get(Account, bt.account_id)
                client = await sm.get_client(acc.id, acc.session_string, acc.proxy)
                channel_entity = await client.get_entity(channel_peer)
                # Join the channel so we can see replies field on posts
                try:
                    from telethon.tl.functions.channels import JoinChannelRequest
                    await client(JoinChannelRequest(channel_entity))
                except Exception:
                    pass
                # Use iter_messages — it returns full reply info unlike get_messages(ids=)
                msg = None
                async for m in client.iter_messages(channel_entity, ids=[message_id]):
                    msg = m
                    break
                if msg is None:
                    # fallback
                    msg = await client.get_messages(channel_entity, ids=message_id)
                if msg:
                    text = (getattr(msg, "message", None) or "").strip()
                    if text:
                        post_text = text[:600]
                    # replies field is only set when comments are enabled for this post
                    replies = getattr(msg, "replies", None)
                    if replies is not None and getattr(replies, "comments", False):
                        comments_enabled = True
                    logger.info("Boost %d: post text %d chars, comments_enabled=%s replies=%s from %s",
                                boost_id, len(post_text), comments_enabled, replies, channel_peer)
                    _working_client = client
                    _working_entity = channel_entity
                    break
            except Exception as e:
                logger.debug("Boost %d: fetch failed via acc %d: %s", boost_id, bt.account_id, e)

    # Fetch real existing comments to give AI full context of current discussion
    if comments_enabled and _working_client and _working_entity:
        try:
            from telethon.tl.functions.messages import GetDiscussionMessageRequest
            discussion = await _working_client(
                GetDiscussionMessageRequest(peer=_working_entity, msg_id=message_id)
            )
            if discussion.chats and discussion.messages:
                disc_group = discussion.chats[0]
                disc_msg_id = discussion.messages[0].id
                async for cmsg in _working_client.iter_messages(
                    disc_group, reply_to=disc_msg_id, limit=15
                ):
                    txt = getattr(cmsg, "message", None) or ""
                    if txt.strip():
                        real_existing_comments.append(txt[:200])
            logger.info("Boost %d: fetched %d real existing comments", boost_id, len(real_existing_comments))
        except Exception as e:
            logger.debug("Boost %d: couldn't fetch existing comments: %s", boost_id, e)

    if channel_peer and not comments_enabled:
        err = f"Канал {channel_peer} не поддерживает комментарии (нет связанного чата обсуждений)"
        logger.error("Boost %d: %s", boost_id, err)
        async with async_session_maker() as db:
            db.add(BoostLog(boost_id=boost_id, account_id=bot_tasks[0].account_id,
                            action="error", text=err))
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

    # Update total_accounts
    async with async_session_maker() as db:
        b = await db.get(BoostTask, boost_id)
        if b:
            b.total_accounts = len(bot_tasks)
            await db.commit()

    # Schedule comments evenly across duration with random jitter
    random.shuffle(bot_tasks)
    n = len(bot_tasks)
    slot_min = duration_min / n if n > 0 else duration_min
    posted_comments: list[str] = []

    sub_tasks = []
    for i, bt in enumerate(bot_tasks):
        jitter = random.uniform(-min(2.0, slot_min / 4), min(2.0, slot_min / 4))
        delay_sec = max(15.0, (i * slot_min + jitter) * 60)
        sub_tasks.append(asyncio.create_task(
            _post_comment(delay_sec, boost_id, channel_peer, message_id,
                          bt.account_id, bt.persona, post_text, topic, posted_comments,
                          real_existing_comments, i)
        ))

    await asyncio.gather(*sub_tasks, return_exceptions=True)

    async with async_session_maker() as db:
        b = await db.get(BoostTask, boost_id)
        if b and b.status == BoostStatus.running:
            b.status = BoostStatus.done
            await db.commit()

    logger.info("Boost %d done — %d accounts, %d comments", boost_id, n, len(posted_comments))


async def _post_comment(
    delay_sec: float,
    boost_id: int,
    channel_peer: str | None,
    message_id: int,
    account_id: int,
    persona: str,
    post_text: str,
    topic: str,
    posted_comments: list[str],
    real_comments: list[str] | None = None,
    style_index: int = 0,
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
        comment = await generate_boost_comment(
            post_text, topic, persona,
            own_comments=list(posted_comments),
            real_comments=real_comments,
            style_index=style_index,
        )

        if channel_peer:
            from telethon.tl.functions.channels import JoinChannelRequest
            channel_entity = await client.get_entity(channel_peer)
            # Join the channel first if not already a member
            try:
                await client(JoinChannelRequest(channel_entity))
            except Exception as join_err:
                logger.debug("Boost %d: acc %d join attempt: %s", boost_id, account_id, join_err)
            # Comment on a channel post (via linked discussion group)
            await client.send_message(channel_entity, comment, comment_to=message_id)
        else:
            # Legacy: reply in bot group
            from telethon.tl.types import PeerChat, PeerChannel
            raw = -int(str(boost_id))  # placeholder — shouldn't be reached for new boosts
            await client.send_message(message_id, comment)

        posted_comments.append(comment)

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
