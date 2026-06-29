"""
Сервис прогрева аккаунтов.
Имитирует поведение обычного пользователя: подписки, чтение, реакции.
Поддерживает сценарии 3/5/7 дней с естественными временными паттернами.
"""
import asyncio
import logging
import random
from datetime import datetime, timedelta
from sqlalchemy import select
from src.database import async_session_maker
from src.models import (
    Account, WarmupTask, WarmupLog, WarmupStatus, AccountEvent
)
import src.session_manager as sm

logger = logging.getLogger(__name__)

# Популярные безопасные каналы для прогрева (разные тематики)
WARMUP_CHANNELS = [
    # Новости
    "@rbc_news", "@lentach", "@russianews", "@breakingmash",
    "@meduzaproject", "@rt_russian", "@bbc_russian",
    # Технологии
    "@vc_ru", "@habr_ru", "@roem_ru", "@dtf_news",
    # Развлечения
    "@humor_ru", "@the_village", "@varlamov_news",
    # Обучение
    "@daily_english", "@itprojects",
    # Общество
    "@durov", "@telegram",
]

# Активные задачи в памяти: task_id → asyncio.Task
_running: dict[int, asyncio.Task] = {}


async def start_warmup(task_id: int) -> None:
    if task_id in _running:
        return
    t = asyncio.create_task(_warmup_loop(task_id), name=f"warmup-{task_id}")
    _running[task_id] = t
    t.add_done_callback(lambda _: _running.pop(task_id, None))
    logger.info("Started warmup task %d", task_id)


async def stop_warmup(task_id: int) -> None:
    t = _running.pop(task_id, None)
    if t and not t.done():
        t.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(t), timeout=3.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass


async def start_all_running() -> None:
    """Возобновить все активные задачи прогрева при старте сервера."""
    async with async_session_maker() as db:
        result = await db.execute(
            select(WarmupTask).where(WarmupTask.status == WarmupStatus.warming)
        )
        tasks = result.scalars().all()
    for task in tasks:
        await start_warmup(task.id)
    if tasks:
        logger.info("Resumed %d warmup task(s)", len(tasks))


async def _log(account_id: int, task_id: int | None, action: str, detail: str = "") -> None:
    async with async_session_maker() as db:
        db.add(WarmupLog(
            account_id=account_id,
            warmup_task_id=task_id,
            action=action,
            detail=detail[:500] if detail else None,
        ))
        acc = await db.get(Account, account_id)
        if acc:
            acc.total_actions = (acc.total_actions or 0) + 1
            acc.last_seen_at = datetime.utcnow()
        await db.commit()


async def _handle_error(account_id: int, error: Exception) -> None:
    """Распознать тип ошибки (бан/флуд/ограничение) и записать в БД."""
    err_str = str(error)
    err_type = type(error).__name__

    event_type = None
    if any(x in err_type for x in ("UserBanned", "PhoneNumberBanned", "UserDeactivated")):
        event_type = "ban"
    elif "FloodWait" in err_type:
        event_type = "flood_wait"
    elif any(x in err_type for x in ("UserRestricted", "ChatWriteForbidden")):
        event_type = "restriction"
    elif "SessionPasswordNeeded" in err_type:
        event_type = "checkpoint"
    elif any(x in err_str.lower() for x in ("banned", "deactivated")):
        event_type = "ban"

    if not event_type:
        return

    async with async_session_maker() as db:
        acc = await db.get(Account, account_id)
        if acc:
            if event_type == "ban":
                acc.bans_count = (acc.bans_count or 0) + 1
                acc.status = "disabled"
                acc.is_active = False
            elif event_type == "restriction":
                acc.restrictions_count = (acc.restrictions_count or 0) + 1
                acc.status = "limited"
        db.add(AccountEvent(
            account_id=account_id,
            event_type=event_type,
            detail=err_str[:500],
        ))
        await db.commit()

    logger.warning("Account %d event: %s — %s", account_id, event_type, err_str[:100])


def _is_active_window(task_id: int) -> bool:
    """
    Определяет, находится ли сейчас активное окно для этого аккаунта.
    Каждый аккаунт имеет свой случайный сдвиг, основанный на task_id,
    чтобы аккаунты не активировались все одновременно.
    """
    now = datetime.utcnow()
    hour = now.hour
    # Смещение для каждого аккаунта: 0-6 часов
    shift = (task_id * 7) % 6
    # Активное окно: 3-5 часов в промежутке 9:00-23:00 UTC
    window_start = 9 + shift
    window_len = random.randint(3, 5)
    window_end = min(window_start + window_len, 23)
    return window_start <= hour < window_end


async def _run_session(account_id: int, task_id: int, client, task: WarmupTask) -> int:
    """
    Одна сессия активности. Возвращает количество выполненных действий.
    """
    from telethon.tl.functions.channels import JoinChannelRequest
    from telethon.tl.functions.messages import SendReactionRequest
    from telethon.tl.types import ReactionEmoji

    actions = 0
    # Целевое количество действий за сессию зависит от дня прогрева
    target = random.randint(3 + task.current_day, 6 + task.current_day * 2)
    target = min(target, 20)

    # --- Действие 1: Подписаться на 1-2 новых канала ---
    new_subs = random.randint(1, 2)
    channels_to_join = random.sample(WARMUP_CHANNELS, min(new_subs, len(WARMUP_CHANNELS)))
    for ch in channels_to_join:
        if actions >= target:
            break
        try:
            entity = await client.get_entity(ch)
            await client(JoinChannelRequest(entity))
            await _log(account_id, task_id, "joined_channel", ch)
            actions += 1
            logger.debug("Warmup %d: joined %s", task_id, ch)
            await asyncio.sleep(random.uniform(60, 240))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            await _handle_error(account_id, e)
            await asyncio.sleep(random.uniform(10, 30))

    # --- Действие 2: Читать сообщения в 2-3 каналах ---
    read_channels = random.sample(WARMUP_CHANNELS, min(3, len(WARMUP_CHANNELS)))
    for ch in read_channels:
        if actions >= target:
            break
        try:
            entity = await client.get_entity(ch)
            count = 0
            async for msg in client.iter_messages(entity, limit=random.randint(8, 20)):
                count += 1
                # Задержка "чтения" каждого сообщения (1-5 сек)
                await asyncio.sleep(random.uniform(1, 5))
            await _log(account_id, task_id, "read_messages", f"{ch}: {count} сообщений")
            actions += 1
            logger.debug("Warmup %d: read %d msgs in %s", task_id, count, ch)
            # Пауза между каналами (1-5 мин)
            await asyncio.sleep(random.uniform(60, 300))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            await _handle_error(account_id, e)

    # --- Действие 3: Поставить реакцию (40% вероятность на 1-2 поста) ---
    if actions < target and random.random() < 0.4:
        react_channels = random.sample(WARMUP_CHANNELS, min(2, len(WARMUP_CHANNELS)))
        for ch in react_channels:
            if actions >= target:
                break
            try:
                entity = await client.get_entity(ch)
                candidates = []
                async for msg in client.iter_messages(entity, limit=15):
                    if msg.text and len(msg.text) > 20:
                        candidates.append(msg)
                if candidates:
                    post = random.choice(candidates)
                    emoji = random.choice(["👍", "❤", "🔥", "👏", "🤔"])
                    await client(SendReactionRequest(
                        peer=entity,
                        msg_id=post.id,
                        reaction=[ReactionEmoji(emoticon=emoji)],
                    ))
                    await _log(account_id, task_id, "reacted", f"{emoji} в {ch}")
                    actions += 1
                    await asyncio.sleep(random.uniform(30, 120))
            except asyncio.CancelledError:
                raise
            except Exception as e:
                await _handle_error(account_id, e)

    # --- Действие 4: Просмотреть диалоги (имитация открытия приложения) ---
    if actions < target:
        try:
            dialog_count = 0
            async for _ in client.iter_dialogs(limit=random.randint(3, 10)):
                dialog_count += 1
                await asyncio.sleep(random.uniform(0.5, 2))
            await _log(account_id, task_id, "opened_app", f"просмотрено диалогов: {dialog_count}")
            actions += 1
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.debug("Warmup %d: dialogs error: %s", task_id, e)

    return actions


async def _warmup_loop(task_id: int) -> None:
    """Главный цикл прогрева. Работает суточными сессиями."""
    target_days = 7  # fallback

    while True:
        try:
            async with async_session_maker() as db:
                task = await db.get(WarmupTask, task_id)
                if not task:
                    break
                if task.status in (WarmupStatus.completed, WarmupStatus.failed):
                    break
                if task.status == WarmupStatus.paused:
                    await asyncio.sleep(60)
                    continue
                target_days = task.target_days
                account = await db.get(Account, task.account_id)

            if not account or not account.is_active:
                async with async_session_maker() as db:
                    t = await db.get(WarmupTask, task_id)
                    if t:
                        t.status = WarmupStatus.failed
                    await db.commit()
                break

            now = datetime.utcnow()

            # Проверить: прогрев завершён?
            if task.started_at:
                days_elapsed = (now - task.started_at).days
                if days_elapsed >= task.target_days:
                    async with async_session_maker() as db:
                        t = await db.get(WarmupTask, task_id)
                        if t:
                            t.status = WarmupStatus.completed
                            t.completed_at = now
                            t.current_day = task.target_days
                        acc = await db.get(Account, task.account_id)
                        if acc:
                            acc.warmup_status = "warmed"
                    logger.info("Warmup task %d completed! %d days", task_id, days_elapsed)
                    break

            # Ждать активного окна
            if not _is_active_window(task_id):
                await asyncio.sleep(random.uniform(20 * 60, 45 * 60))
                continue

            # Запустить сессию
            try:
                client = await sm.get_client(account.id, account.session_string, account.proxy)
            except Exception as e:
                logger.error("Warmup %d: client error: %s", task_id, e)
                await _handle_error(account.id, e)
                await asyncio.sleep(30 * 60)
                continue

            logger.info("Warmup %d: starting session (day %d/%d)",
                        task_id, (task.current_day or 0) + 1, task.target_days)

            done = await _run_session(account.id, task_id, client, task)

            # Обновить статистику
            async with async_session_maker() as db:
                t = await db.get(WarmupTask, task_id)
                if t:
                    t.actions_today = (t.actions_today or 0) + done
                    t.actions_total = (t.actions_total or 0) + done
                    t.last_activity_at = datetime.utcnow()
                    if not t.started_at:
                        t.started_at = datetime.utcnow()
                        acc = await db.get(Account, task.account_id)
                        if acc:
                            acc.warmup_status = "warming"
                            acc.warmup_started_at = t.started_at
                    if t.started_at:
                        t.current_day = (datetime.utcnow() - t.started_at).days + 1
                await db.commit()

            logger.info("Warmup %d: session done, %d actions", task_id, done)

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Warmup loop %d error: %s", task_id, exc, exc_info=True)

        # Пауза между сессиями: 45 мин — 2 часа (естественные интервалы)
        sleep_sec = random.uniform(45 * 60, 2 * 60 * 60)
        logger.debug("Warmup %d: sleeping %.0f min", task_id, sleep_sec / 60)
        await asyncio.sleep(sleep_sec)

    logger.info("Warmup task %d loop ended", task_id)
