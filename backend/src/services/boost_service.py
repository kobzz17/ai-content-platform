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

    # Fetch the channel post text using the first available account
    post_text = ""
    if channel_peer:
        for bt in bot_tasks[:3]:
            try:
                async with async_session_maker() as db:
                    acc = await db.get(Account, bt.account_id)
                client = await sm.get_client(acc.id, acc.session_string, acc.proxy)
                channel_entity = await client.get_entity(channel_peer)
                msg = await client.get_messages(channel_entity, ids=message_id)
                if msg:
                    text = (getattr(msg, "message", None) or "").strip()
                    if text:
                        post_text = text[:600]
                        logger.info("Boost %d: fetched post text (%d chars) from %s",
                                    boost_id, len(post_text), channel_peer)
                        break
            except Exception as e:
                logger.debug("Boost %d: fetch failed via acc %d: %s", boost_id, bt.account_id, e)

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
                          bt.account_id, bt.persona, post_text, topic, posted_comments)
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
        comment = await generate_boost_comment(post_text, topic, persona, list(posted_comments))

        if channel_peer:
            # Comment on a channel post (posts in linked discussion group)
            channel_entity = await client.get_entity(channel_peer)
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
