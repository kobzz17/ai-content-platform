import asyncio
import logging
import random
from datetime import datetime, timedelta
from sqlalchemy import select
from src.database import async_session_maker
from src.models import BotTask, BotLog, TaskStatus, Account
import src.session_manager as sm

logger = logging.getLogger(__name__)

_running: dict[int, asyncio.Task] = {}

# Shared: when did last message appear in the group (any bot)
# Used to detect "active window" and boost reply chance during conversation burst
_last_group_activity: datetime = datetime.utcnow() - timedelta(hours=12)
_BURST_WINDOW_MIN = 30  # minutes — how long a burst stays "warm"

# Global minimum gap between any two bot messages (prevents flooding)
_last_bot_post: datetime = datetime.utcnow() - timedelta(hours=12)
_MIN_BOT_INTERVAL_MIN = 8  # minimum minutes between any bot messages


def _resolve_chat_peer(chat_id: int):
    from telethon.tl.types import PeerChat, PeerChannel
    if chat_id < 0:
        raw = -chat_id
        if raw > 1_000_000_000_000:
            return PeerChannel(raw - 1_000_000_000_000)
        return PeerChat(raw)
    return chat_id


async def start_task(task_id: int) -> None:
    if task_id in _running:
        return
    t = asyncio.create_task(_bot_loop(task_id), name=f"bot-{task_id}")
    _running[task_id] = t
    t.add_done_callback(lambda _: _running.pop(task_id, None))
    logger.info("Started bot task %d", task_id)


async def stop_task(task_id: int) -> None:
    t = _running.pop(task_id, None)
    if t and not t.done():
        t.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(t), timeout=3.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass


async def start_all_running() -> None:
    async with async_session_maker() as db:
        result = await db.execute(
            select(BotTask).where(BotTask.status == TaskStatus.running)
        )
        tasks = result.scalars().all()
    for task in tasks:
        await start_task(task.id)
    if tasks:
        logger.info("Resumed %d bot task(s) from DB", len(tasks))


async def _fetch_news_snippet(account_id: int, proxy: str | None) -> str:
    """Grab a recent post from a subscribed channel to share in the group."""
    from src.models import ChannelTask, ChannelSubscription
    from sqlalchemy import select as sa_select
    try:
        async with async_session_maker() as db:
            r = await db.execute(sa_select(ChannelTask).where(ChannelTask.account_id == account_id))
            ctask = r.scalars().first()
            if not ctask:
                return ""
            r2 = await db.execute(sa_select(ChannelSubscription).where(ChannelSubscription.task_id == ctask.id))
            subs = r2.scalars().all()
        if not subs:
            return ""
        sub = random.choice(subs)
        chan = sub.channel_username or sub.channel_title or ""
        if not chan:
            return ""
        from src.database import async_session_maker as asm
        from src.models import Account
        async with async_session_maker() as db:
            acc = await db.get(Account, account_id)
        client = await sm.get_client(account_id, acc.session_string, acc.proxy)
        async for msg in client.iter_messages(chan, limit=5):
            if msg.text and len(msg.text) > 40:
                return msg.text[:400]
    except Exception:
        pass
    return ""


async def _bot_loop(task_id: int) -> None:
    global _last_group_activity, _last_bot_post
    from src.services.ai_service import generate_bot_reply, generate_new_topic

    last_msg_id: int = 0
    last_replied: datetime = datetime.utcnow() - timedelta(hours=24)  # per-bot cooldown
    _REPLY_COOLDOWN_MIN = 40  # don't reply twice within 40 min

    # Heavy random initial stagger: 0–20 minutes so bots never align
    await asyncio.sleep(random.uniform(0, 1200))

    # Load task to get proactive_interval, then stagger proactive start randomly
    async with async_session_maker() as db:
        _init_task = await db.get(BotTask, task_id)
        _pi = _init_task.proactive_interval if _init_task and _init_task.proactive_interval else 60

    # First proactive post within 10-60 min of startup (spread bots out a bit)
    # After that, full proactive_interval applies
    first_post_delay = random.uniform(10, 60)
    last_proactive = datetime.utcnow() - timedelta(minutes=_pi) + timedelta(minutes=first_post_delay)

    async with async_session_maker() as db:
        task = await db.get(BotTask, task_id)
        account = await db.get(Account, task.account_id)

    if account.session_string == "DEMO":
        return

    try:
        client = await sm.get_client(account.id, account.session_string, account.proxy)
        chat_peer = _resolve_chat_peer(task.chat_id)
        async for msg in client.iter_messages(chat_peer, limit=1):
            last_msg_id = msg.id
    except Exception as exc:
        logger.warning("Task %d: seeding last_msg_id failed: %s", task_id, exc)

    while True:
        try:
            async with async_session_maker() as db:
                task = await db.get(BotTask, task_id)
                if not task or task.status == TaskStatus.stopped:
                    break
                if task.status == TaskStatus.paused:
                    await asyncio.sleep(random.uniform(30, 90))
                    continue
                account = await db.get(Account, task.account_id)

            client = await sm.get_client(account.id, account.session_string, account.proxy)
            chat_peer = _resolve_chat_peer(task.chat_id)

            # Collect new messages since last poll (only from others)
            new_messages = []
            new_max_id = last_msg_id
            async for msg in client.iter_messages(chat_peer, limit=50, min_id=last_msg_id):
                if msg.id > new_max_id:
                    new_max_id = msg.id
                if msg.text and not msg.out:
                    new_messages.append(msg)
            last_msg_id = new_max_id

            if new_messages:
                _last_group_activity = datetime.utcnow()

            # Reply probability: higher during burst window, nearly zero outside
            minutes_since_activity = (datetime.utcnow() - _last_group_activity).total_seconds() / 60
            in_burst = minutes_since_activity < _BURST_WINDOW_MIN
            effective_prob = task.reply_probability if in_burst else max(task.reply_probability // 6, 3)

            since_last_reply = (datetime.utcnow() - last_replied).total_seconds() / 60
            since_last_bot = (datetime.utcnow() - _last_bot_post).total_seconds() / 60
            can_reply = since_last_reply >= _REPLY_COOLDOWN_MIN and since_last_bot >= _MIN_BOT_INTERVAL_MIN

            if new_messages and can_reply and random.randint(1, 100) <= effective_prob:
                trigger = new_messages[0]
                trigger_text = trigger.text
                trigger_sender = getattr(trigger.sender, "first_name", None) or "собеседник"

                history = []
                async for msg in client.iter_messages(chat_peer, limit=12):
                    if msg.text:
                        sender = "Я" if msg.out else (
                            getattr(msg.sender, "first_name", None) or "Участник"
                        )
                        history.append({"sender": sender, "text": msg.text})
                history = list(reversed(history))

                # Human delay: 1–8 minutes during burst, longer outside
                if in_burst:
                    delay = random.uniform(60, 480)
                else:
                    delay = random.uniform(300, 1800)
                await asyncio.sleep(delay)

                reply = await generate_bot_reply(
                    history, task.persona,
                    trigger_text=trigger_text,
                    trigger_sender=trigger_sender,
                )
                await client.send_message(chat_peer, reply)
                _last_group_activity = datetime.utcnow()
                _last_bot_post = datetime.utcnow()

                async with async_session_maker() as db:
                    db.add(BotLog(task_id=task_id, action="replied", text=reply))
                    t = await db.get(BotTask, task_id)
                    if t:
                        t.last_action_at = datetime.utcnow()
                    await db.commit()

                last_replied = datetime.utcnow()
                last_proactive = datetime.utcnow()
                logger.info("Task %d replied in chat %d", task_id, task.chat_id)

            # Proactive: one bot posts something new, triggering a burst
            since_last_bot_proactive = (datetime.utcnow() - _last_bot_post).total_seconds() / 60
            if (task.proactive_interval and
                    datetime.utcnow() - last_proactive >= timedelta(minutes=task.proactive_interval) and
                    since_last_bot_proactive >= _MIN_BOT_INTERVAL_MIN):
                # 30% chance: grab a real news snippet from subscribed channels
                news = ""
                if random.randint(1, 100) <= 30:
                    news = await _fetch_news_snippet(account.id, account.proxy)
                topic = await generate_new_topic(task.persona, news_snippet=news)
                await client.send_message(chat_peer, topic)
                _last_group_activity = datetime.utcnow()
                _last_bot_post = datetime.utcnow()

                async with async_session_maker() as db:
                    db.add(BotLog(task_id=task_id, action="topic_posted", text=topic))
                    t = await db.get(BotTask, task_id)
                    if t:
                        t.last_action_at = datetime.utcnow()
                    await db.commit()

                last_proactive = datetime.utcnow()
                logger.info("Task %d posted topic in chat %d", task_id, task.chat_id)

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Task %d error: %s", task_id, exc, exc_info=True)
            try:
                async with async_session_maker() as db:
                    db.add(BotLog(task_id=task_id, action="error", text=str(exc)))
                    await db.commit()
            except Exception:
                pass

        # Poll interval: every 2-8 minutes
        await asyncio.sleep(random.uniform(120, 480))

    logger.info("Bot task %d stopped", task_id)
