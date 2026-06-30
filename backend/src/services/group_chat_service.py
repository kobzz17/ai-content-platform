"""
Координированный групповой чат для нескольких аккаунтов.

Один asyncio-цикл управляет всеми аккаунтами в группе:
- Решает кто и когда пишет (не все одновременно)
- Шарит новости из каналов с комментарием
- Запускает цепочки обсуждений
- Реагирует на чужие сообщения
"""
import asyncio
import json
import logging
import random
from datetime import datetime, timedelta
from sqlalchemy import select
from src.database import async_session_maker
from src.models import Account, GroupChatSession, GroupChatLog
import src.session_manager as sm

logger = logging.getLogger(__name__)

_running: dict[int, asyncio.Task] = {}

# Каналы для шаринга новостей
NEWS_CHANNELS = [
    "@rbc_news", "@lentach", "@breakingmash", "@meduzaproject",
    "@rt_russian", "@bbc_russian", "@vc_ru", "@habr_ru", "@durov",
]

# Персонажи для каждого аккаунта (по account_id)
PERSONAS: dict[int, str] = {
    5:  "IT-инженер Александр, интересуется технологиями и ИИ, иногда занудный но умный",
    6:  "Артём, активный молодой человек, следит за новостями, любит обсудить события дня",
    7:  "Роман, спортивный и практичный, конкретен в суждениях, иногда скептичен",
    8:  "Павел, предприниматель, смотрит на всё с практической и экономической стороны",
    9:  "Илья, студент, любознательный, задаёт много вопросов, иногда наивный",
    10: "Никита, путешественник с широким кругозором, культурный, вносит неожиданные точки зрения",
}


async def start_session(session_id: int) -> None:
    if session_id in _running:
        return
    t = asyncio.create_task(_session_loop(session_id), name=f"group-{session_id}")
    _running[session_id] = t
    t.add_done_callback(lambda _: _running.pop(session_id, None))
    logger.info("Started group chat session %d", session_id)


async def stop_session(session_id: int) -> None:
    t = _running.pop(session_id, None)
    if t and not t.done():
        t.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(t), timeout=3.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass


async def start_all_running() -> None:
    async with async_session_maker() as db:
        result = await db.execute(
            select(GroupChatSession).where(GroupChatSession.status == "running")
        )
        sessions = result.scalars().all()
    for s in sessions:
        await start_session(s.id)
    if sessions:
        logger.info("Resumed %d group chat session(s)", len(sessions))


async def _log(session_id: int, account_id: int, action: str, text: str = "") -> None:
    async with async_session_maker() as db:
        db.add(GroupChatLog(
            session_id=session_id,
            account_id=account_id,
            action=action,
            text=text[:1000] if text else None,
        ))
        await db.commit()


async def _get_recent_history(client, chat_id: int, limit: int = 15) -> list[dict]:
    """Получить последние сообщения в группе."""
    history = []
    try:
        async for msg in client.iter_messages(chat_id, limit=limit):
            if msg.text:
                sender = getattr(msg.sender, "first_name", None) or "Участник"
                history.append({
                    "id": msg.id,
                    "sender": sender,
                    "sender_id": getattr(msg.sender, "id", 0),
                    "text": msg.text,
                    "is_out": msg.out,
                })
        history.reverse()
    except Exception as e:
        logger.debug("History fetch error: %s", e)
    return history


async def _action_reply(client, chat_id: int, account_id: int, session_id: int,
                         history: list[dict], persona: str) -> bool:
    """Ответить на недавнее сообщение другого участника."""
    from src.services.ai_service import generate_group_reply

    # Найти последнее сообщение НЕ от этого аккаунта
    others = [m for m in history[-8:] if not m["is_out"]]
    if not others:
        return False

    target = random.choice(others[-3:])  # одно из последних 3 чужих
    reply_text = await generate_group_reply(history, persona, target["sender"])

    delay = random.uniform(20, 120)
    await asyncio.sleep(delay)
    await client.send_message(chat_id, reply_text, reply_to=target["id"])
    await _log(session_id, account_id, "reply", reply_text)
    logger.info("Group %d: account %d replied to %s", session_id, account_id, target["sender"])
    return True


async def _action_share_news(client, chat_id: int, account_id: int,
                              session_id: int, persona: str) -> bool:
    """Взять пост из новостного канала и поделиться с комментарием."""
    from src.services.ai_service import generate_news_share

    channel = random.choice(NEWS_CHANNELS)
    try:
        entity = await client.get_entity(channel)
        posts = []
        async for msg in client.iter_messages(entity, limit=20):
            if msg.text and len(msg.text) > 80:
                posts.append(msg)
        if not posts:
            return False

        post = random.choice(posts[:10])
        commentary = await generate_news_share(post.text[:600], channel, persona)

        # Форвард + комментарий, или просто текст со ссылкой
        try:
            await client.forward_messages(chat_id, post.id, entity)
            await asyncio.sleep(random.uniform(3, 10))
            await client.send_message(chat_id, commentary)
        except Exception:
            # Если форвард не разрешён — цитата + ссылка
            short = post.text[:300] + ("..." if len(post.text) > 300 else "")
            msg_text = f"{commentary}\n\n📰 {channel}:\n{short}"
            await client.send_message(chat_id, msg_text)

        await _log(session_id, account_id, "news", f"{channel}: {commentary}")
        logger.info("Group %d: account %d shared news from %s", session_id, account_id, channel)
        return True
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.debug("News share error from %s: %s", channel, e)
        return False


async def _action_start_topic(client, chat_id: int, account_id: int,
                               session_id: int, persona: str) -> bool:
    """Начать новую тему разговора."""
    from src.services.ai_service import generate_new_topic

    topic = await generate_new_topic(persona)
    await client.send_message(chat_id, topic)
    await _log(session_id, account_id, "topic", topic)
    logger.info("Group %d: account %d started topic", session_id, account_id)
    return True


async def _is_active_hour() -> bool:
    hour = datetime.utcnow().hour
    return 7 <= hour < 22  # активны с 7 до 22 UTC


async def _get_last_msg_time(client, chat_id: int) -> datetime | None:
    """Время последнего сообщения в чате."""
    try:
        async for msg in client.iter_messages(chat_id, limit=1):
            return msg.date.replace(tzinfo=None)
    except Exception:
        pass
    return None


async def _session_loop(session_id: int) -> None:
    """
    Главный цикл сессии с тремя состояниями:
    - IDLE: долгая пауза (20-60 мин), потом кто-то начинает тему или кидает новость
    - ACTIVE: активная беседа, быстрые ответы (30 сек - 2 мин между сообщениями)
    - COOLING: беседа затихает, пауза 8-15 мин перед следующей волной
    """
    last_action: dict[int, datetime] = {}
    state = "idle"
    burst_count = 0       # сколько сообщений уже в текущей волне
    burst_max = 0         # сколько сообщений запланировано в волне
    last_msg_time: datetime | None = None
    burst_starter: int | None = None  # кто начал текущую беседу

    while True:
        try:
            async with async_session_maker() as db:
                session = await db.get(GroupChatSession, session_id)
                if not session or session.status == "stopped":
                    break
                if session.status == "paused":
                    await asyncio.sleep(60)
                    continue
                account_ids: list[int] = json.loads(session.account_ids)

                if session.started_at:
                    elapsed = (datetime.utcnow() - session.started_at).total_seconds()
                    if elapsed >= session.duration_days * 86400:
                        session.status = "stopped"
                        await db.commit()
                        logger.info("Group session %d completed", session_id)
                        break

            if not await _is_active_hour():
                await asyncio.sleep(random.uniform(20 * 60, 40 * 60))
                continue

            now = datetime.utcnow()

            # ── Определить состояние ─────────────────────────────────────────
            if state == "active":
                if burst_count >= burst_max:
                    # Волна закончилась — переходим в cooling
                    state = "cooling"
                    burst_count = 0
                    logger.debug("Group %d: burst done, cooling down", session_id)
                    await asyncio.sleep(random.uniform(8 * 60, 15 * 60))
                    continue

            elif state == "cooling":
                # После паузы проверяем: есть ли активность в чате?
                state = "idle"
                continue

            # ── Выбрать аккаунт ──────────────────────────────────────────────
            if state == "active":
                # Во время беседы — не тот кто говорил последним и не стартер
                candidates = [
                    a for a in account_ids
                    if a != burst_starter and
                    (now - last_action.get(a, datetime.min)).total_seconds() > 20
                ]
                if not candidates:
                    candidates = account_ids
            else:
                # В idle — тот кто давно молчал
                candidates = sorted(
                    account_ids,
                    key=lambda aid: last_action.get(aid, datetime.min)
                )
                account_id = candidates[0]
                # Минимум 20 минут молчания перед новой инициативой
                if (now - last_action.get(account_id, datetime.min)).total_seconds() < 20 * 60:
                    await asyncio.sleep(random.uniform(5 * 60, 12 * 60))
                    continue

            account_id = random.choice(candidates[:3]) if len(candidates) > 1 else candidates[0]

            async with async_session_maker() as db:
                account = await db.get(Account, account_id)
            if not account or not account.is_active:
                continue

            persona = PERSONAS.get(account_id, "обычный пользователь Telegram")

            try:
                client = await sm.get_client(account.id, account.session_string, account.proxy)
                history = await _get_recent_history(client, session.chat_id)

                if state == "idle":
                    # Начать новую беседу: тема или новость
                    action = random.choices(["topic", "news"], weights=[45, 55])[0]
                    if action == "news":
                        ok = await _action_share_news(client, session.chat_id, account_id, session_id, persona)
                        if not ok:
                            await _action_start_topic(client, session.chat_id, account_id, session_id, persona)
                    else:
                        await _action_start_topic(client, session.chat_id, account_id, session_id, persona)

                    # Запустить волну: 3-6 ответов от других
                    state = "active"
                    burst_max = random.randint(3, 6)
                    burst_count = 0
                    burst_starter = account_id
                    last_action[account_id] = datetime.utcnow()

                    # Первый ответ придёт через 30-90 секунд
                    await asyncio.sleep(random.uniform(30, 90))

                elif state == "active":
                    # Ответить на что-то в беседе
                    others = [m for m in history[-6:] if not m["is_out"]]
                    if others:
                        await _action_reply(client, session.chat_id, account_id, session_id, history, persona)
                    else:
                        await _action_start_topic(client, session.chat_id, account_id, session_id, persona)

                    burst_count += 1
                    last_action[account_id] = datetime.utcnow()

                    # Пауза между сообщениями в беседе: 25 сек - 2 мин
                    # Иногда кто-то "задумывается" подольше (до 4 мин)
                    if random.random() < 0.15:
                        await asyncio.sleep(random.uniform(2 * 60, 4 * 60))
                    else:
                        await asyncio.sleep(random.uniform(25, 110))

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("Group %d account %d error: %s", session_id, account_id, e)
                await asyncio.sleep(30)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Group session %d loop error: %s", session_id, e, exc_info=True)
            await asyncio.sleep(60)

    logger.info("Group chat session %d loop ended", session_id)
