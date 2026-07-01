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


async def _bot_loop(task_id: int) -> None:
    from src.services.ai_service import generate_bot_reply, generate_new_topic

    last_msg_id: int = 0
    # Each bot gets a fully random initial offset (0–8 min) so they never sync up
    await asyncio.sleep(random.uniform(0, 480))

    # last_proactive in the far past so first proactive fires after proactive_interval minutes
    last_proactive = datetime.utcnow() - timedelta(hours=24)

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
                    await asyncio.sleep(random.uniform(10, 30))
                    continue
                account = await db.get(Account, task.account_id)

            client = await sm.get_client(account.id, account.session_string, account.proxy)
            chat_peer = _resolve_chat_peer(task.chat_id)

            # Collect new messages since last poll (only from others, not self)
            new_messages = []
            new_max_id = last_msg_id
            async for msg in client.iter_messages(chat_peer, limit=50, min_id=last_msg_id):
                if msg.id > new_max_id:
                    new_max_id = msg.id
                if msg.text and not msg.out:
                    new_messages.append(msg)
            last_msg_id = new_max_id

            if new_messages and random.randint(1, 100) <= task.reply_probability:
                # Pick the most recent interesting message to specifically engage with
                trigger = new_messages[0]  # most recent (iter_messages returns newest first)
                trigger_text = trigger.text
                trigger_sender = getattr(trigger.sender, "first_name", None) or "собеседник"

                # Build conversation history for context
                history = []
                async for msg in client.iter_messages(chat_peer, limit=12):
                    if msg.text:
                        sender = "Я" if msg.out else (
                            getattr(msg.sender, "first_name", None) or "Участник"
                        )
                        history.append({"sender": sender, "text": msg.text})
                history = list(reversed(history))

                # Human-like delay before responding
                delay = random.uniform(task.min_delay, task.max_delay)
                await asyncio.sleep(delay)

                reply = await generate_bot_reply(
                    history, task.persona,
                    trigger_text=trigger_text,
                    trigger_sender=trigger_sender,
                )
                await client.send_message(chat_peer, reply)

                async with async_session_maker() as db:
                    db.add(BotLog(task_id=task_id, action="replied", text=reply))
                    t = await db.get(BotTask, task_id)
                    if t:
                        t.last_action_at = datetime.utcnow()
                    await db.commit()

                last_proactive = datetime.utcnow()
                logger.info("Task %d replied in chat %d", task_id, task.chat_id)

            # Proactive: throw something into the chat on own initiative
            if (task.proactive_interval and
                    datetime.utcnow() - last_proactive >= timedelta(minutes=task.proactive_interval)):
                topic = await generate_new_topic(task.persona)
                await client.send_message(chat_peer, topic)

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

        # Fully random sleep so no two bots are in sync
        await asyncio.sleep(random.uniform(20, 110))

    logger.info("Bot task %d stopped", task_id)
