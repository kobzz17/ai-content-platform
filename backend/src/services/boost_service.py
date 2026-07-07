"""Boost service — coordinates all bot accounts to comment on a specific group post."""
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


def _resolve_chat_peer(chat_id: int):
    from telethon.tl.types import PeerChat, PeerChannel
    if chat_id < 0:
        raw = -chat_id
        if raw > 1_000_000_000_000:
            return PeerChannel(raw - 1_000_000_000_000)
        return PeerChat(raw)
    return chat_id


async def start_boost(boost_id: int) -> None:
    if boost_id in _running:
        return
    t = asyncio.create_task(_boost_campaign(boost_id), name=f"boost-{boost_id}")
    _running[boost_id] = t
    t.add_done_callback(lambda _: _running.pop(boost_id, None))
    logger.info("Started boost campaign %d", boost_id)


async def start_all_running() -> None:
    """Resume boost campaigns that were running when the server last stopped."""
    async with async_session_maker() as db:
        r = await db.execute(
            select(BoostTask).where(BoostTask.status == BoostStatus.running)
        )
        boosts = r.scalars().all()
    for b in boosts:
        await start_boost(b.id)
    if boosts:
        logger.info("Resumed %d boost campaign(s) from DB", len(boosts))


async def stop_boost(boost_id: int) -> None:
    t = _running.pop(boost_id, None)
    if t and not t.done():
        t.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(t), timeout=3.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass


async def _boost_campaign(boost_id: int) -> None:
    from src.services.ai_service import analyze_post_for_boost

    async with async_session_maker() as db:
        boost = await db.get(BoostTask, boost_id)
        if not boost:
            return
        chat_id = boost.chat_id
        message_id = boost.message_id
        topic = boost.topic
        duration_min = boost.duration_minutes

    # Get all running BotTasks for this chat
    async with async_session_maker() as db:
        r = await db.execute(
            select(BotTask).where(
                BotTask.status == TaskStatus.running,
                BotTask.chat_id == chat_id,
            )
        )
        bot_tasks = list(r.scalars().all())

    if not bot_tasks:
        logger.warning("Boost %d: no running BotTasks for chat_id=%d", boost_id, chat_id)
        async with async_session_maker() as db:
            b = await db.get(BoostTask, boost_id)
            if b:
                b.status = BoostStatus.done
                await db.commit()
        return

    # Fetch the target message text (supports text-only and media+caption)
    chat_peer = _resolve_chat_peer(chat_id)
    post_text = ""
    for bt in bot_tasks:
        try:
            async with async_session_maker() as db:
                acc = await db.get(Account, bt.account_id)
            client = await sm.get_client(acc.id, acc.session_string, acc.proxy)

            # For basic Telegram groups, fetching by ID requires scanning history.
            # Use offset_id=message_id+1 limit=1 to land exactly on the message.
            msg = None
            async for m in client.iter_messages(chat_peer, limit=1, offset_id=message_id + 1):
                if m.id == message_id:
                    msg = m
                break

            if msg:
                text = (getattr(msg, "message", None) or "").strip()
                logger.info("Boost %d: msg %d fetched, text=%d chars, has_media=%s",
                            boost_id, message_id, len(text), bool(msg.media))
                if text:
                    post_text = text[:600]
                    break
            else:
                logger.debug("Boost %d: msg %d not found (acc %d)", boost_id, message_id, bt.account_id)
        except Exception as e:
            logger.debug("Boost %d: failed to fetch message via acc %d: %s", boost_id, bt.account_id, e)

    # Auto-generate topic if not specified
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

    # Update total_accounts count
    async with async_session_maker() as db:
        b = await db.get(BoostTask, boost_id)
        if b:
            b.total_accounts = len(bot_tasks)
            await db.commit()

    # Stagger comments evenly across duration
    random.shuffle(bot_tasks)
    n = len(bot_tasks)
    slot_min = duration_min / n if n > 0 else duration_min
    posted_comments: list[str] = []  # shared; readable by later slots for variety

    sub_tasks = []
    for i, bt in enumerate(bot_tasks):
        jitter = random.uniform(-min(2.0, slot_min / 4), min(2.0, slot_min / 4))
        delay_sec = max(10.0, (i * slot_min + jitter) * 60)
        sub_tasks.append(asyncio.create_task(
            _post_comment(delay_sec, boost_id, chat_id, message_id, bt.account_id, bt.persona,
                          post_text, topic, posted_comments)
        ))

    await asyncio.gather(*sub_tasks, return_exceptions=True)

    async with async_session_maker() as db:
        b = await db.get(BoostTask, boost_id)
        if b and b.status == BoostStatus.running:
            b.status = BoostStatus.done
            await db.commit()

    logger.info("Boost %d done — %d accounts, %d comments posted", boost_id, n, len(posted_comments))


async def _post_comment(
    delay_sec: float,
    boost_id: int,
    chat_id: int,
    message_id: int,
    account_id: int,
    persona: str,
    post_text: str,
    topic: str,
    posted_comments: list[str],
) -> None:
    from src.services.ai_service import generate_boost_comment

    await asyncio.sleep(delay_sec)

    # Bail out if campaign was cancelled while we were sleeping
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
        chat_peer = _resolve_chat_peer(chat_id)

        comment = await generate_boost_comment(post_text, topic, persona, list(posted_comments))
        await client.send_message(chat_peer, comment, reply_to=message_id)
        posted_comments.append(comment)

        async with async_session_maker() as db:
            db.add(BoostLog(boost_id=boost_id, account_id=account_id, action="commented", text=comment))
            b = await db.get(BoostTask, boost_id)
            if b:
                b.comments_posted += 1
            await db.commit()

        logger.info("Boost %d: acc %d commented on msg %d", boost_id, account_id, message_id)

    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error("Boost %d: acc %d failed: %s", boost_id, account_id, e)
        try:
            async with async_session_maker() as db:
                db.add(BoostLog(boost_id=boost_id, account_id=account_id, action="error", text=str(e)[:300]))
                await db.commit()
        except Exception:
            pass
