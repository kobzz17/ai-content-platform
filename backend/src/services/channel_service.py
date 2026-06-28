import asyncio
import logging
import random
from datetime import datetime, timedelta
from sqlalchemy import select, func
from src.database import async_session_maker
from src.models import ChannelTask, ChannelSubscription, ChannelLog, TaskStatus, SessionMode, Account
import src.session_manager as sm

logger = logging.getLogger(__name__)

REACTIONS = ["👍", "❤", "🔥", "👏", "🤔", "🎉", "😮"]

_running: dict[int, asyncio.Task] = {}
_triggers: dict[int, asyncio.Event] = {}  # set to wake up the loop early


async def start_task(task_id: int) -> None:
    if task_id in _running:
        return
    t = asyncio.create_task(_channel_loop(task_id), name=f"ch-{task_id}")
    _running[task_id] = t
    t.add_done_callback(lambda _: _running.pop(task_id, None))
    logger.info("Started channel task %d", task_id)


async def trigger_now(task_id: int) -> None:
    """Wake up a sleeping task to run one iteration immediately."""
    if task_id not in _triggers:
        _triggers[task_id] = asyncio.Event()
    _triggers[task_id].set()


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
            select(ChannelTask).where(ChannelTask.status == TaskStatus.running)
        )
        tasks = result.scalars().all()
    for task in tasks:
        await start_task(task.id)
    if tasks:
        logger.info("Resumed %d channel task(s)", len(tasks))


async def _daily_action_count(task_id: int) -> int:
    since = datetime.utcnow() - timedelta(hours=24)
    async with async_session_maker() as db:
        result = await db.execute(
            select(func.count()).where(
                ChannelLog.task_id == task_id,
                ChannelLog.created_at >= since,
                ChannelLog.action.in_(["commented", "reacted"]),
            )
        )
        return result.scalar() or 0


def _check_session_mode(task: ChannelTask) -> str | None:
    """Return a reason string if the task should be skipped this iteration, else None."""
    now = datetime.utcnow()
    mode = task.session_mode or SessionMode.always

    if mode == SessionMode.always:
        return None

    if mode == SessionMode.random:
        if task.offline_until and now < task.offline_until:
            delta = task.offline_until - now
            mins = int(delta.total_seconds() / 60)
            return f"оффлайн ещё {mins} мин"
        # Randomly decide to go offline: 25% chance each new iteration
        if random.randint(1, 100) <= 25:
            return "случайный офлайн-период"
        return None

    if mode == SessionMode.work_hours:
        hour = now.hour  # UTC+0; adjust if needed
        if not (9 <= hour < 20):
            return f"вне рабочих часов (сейчас {hour}:00 UTC)"
        return None

    if mode == SessionMode.evening:
        hour = now.hour
        if not (18 <= hour < 23):
            return f"вне вечерних часов (сейчас {hour}:00 UTC)"
        return None

    return None


async def _channel_loop(task_id: int) -> None:
    from src.services.ai_service import generate_channel_comment

    check_interval = 60  # fallback if task can't be loaded
    while True:
        try:
            async with async_session_maker() as db:
                task = await db.get(ChannelTask, task_id)
                if not task or task.status == TaskStatus.stopped:
                    break
                if task.status == TaskStatus.paused:
                    await asyncio.sleep(30)
                    continue
                check_interval = task.check_interval
                account = await db.get(Account, task.account_id)

            if not account:
                logger.error("Task %d: account not found, stopping", task_id)
                break

            if account.session_string == "DEMO":
                await asyncio.sleep(60)
                continue

            # Check session mode: skip this iteration if "offline"
            skip_reason = _check_session_mode(task)
            if skip_reason:
                logger.info("Task %d: skipping (session mode %s: %s)", task_id, task.session_mode, skip_reason)
                # After random offline, update offline_until
                if task.session_mode == SessionMode.random and not task.offline_until:
                    offline_hours = random.uniform(1, 6)
                    async with async_session_maker() as db:
                        t = await db.get(ChannelTask, task_id)
                        if t:
                            t.offline_until = datetime.utcnow() + timedelta(hours=offline_hours)
                        await db.commit()
                    logger.info("Task %d: going offline for %.1fh", task_id, offline_hours)
                await asyncio.sleep(30 * 60)  # recheck in 30 min
                continue

            # Clear offline_until if we're now active again
            if task.offline_until:
                async with async_session_maker() as db:
                    t = await db.get(ChannelTask, task_id)
                    if t:
                        t.offline_until = None
                    await db.commit()

            client = await sm.get_client(account.id, account.session_string, account.proxy)

            daily_count = await _daily_action_count(task_id)
            if daily_count >= task.max_daily_actions:
                logger.info("Task %d hit daily limit (%d), sleeping", task_id, task.max_daily_actions)
                await asyncio.sleep(task.check_interval * 60)
                continue

            # ── Phase 1: Find and subscribe to new channels ───────────────
            async with async_session_maker() as db:
                subs_result = await db.execute(
                    select(ChannelSubscription).where(ChannelSubscription.task_id == task_id)
                )
                subscriptions = subs_result.scalars().all()

            if len(subscriptions) < task.max_channels:
                keywords = [k.strip() for k in task.keywords.split(",")]
                keyword = random.choice(keywords)
                await _find_and_subscribe(client, task_id, keyword, task.max_channels, subscriptions)

            # ── Phase 2: Check 1-2 random channels per iteration ─────────
            async with async_session_maker() as db:
                subs_result = await db.execute(
                    select(ChannelSubscription).where(ChannelSubscription.task_id == task_id)
                )
                subscriptions = subs_result.scalars().all()

            if subscriptions:
                pick_count = random.randint(1, min(2, len(subscriptions)))
                to_process = random.sample(subscriptions, pick_count)

                for i, sub in enumerate(to_process):
                    if daily_count >= task.max_daily_actions:
                        break
                    # Human-like pause between channels (5-20 min)
                    if i > 0:
                        await asyncio.sleep(random.uniform(60, 3 * 60))
                    daily_count += await _process_channel(
                        client, task, sub, generate_channel_comment
                    )

            # Update last_run_at
            async with async_session_maker() as db:
                t = await db.get(ChannelTask, task_id)
                if t:
                    t.last_run_at = datetime.utcnow()
                await db.commit()

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Channel task %d error: %s", task_id, exc, exc_info=True)
            async with async_session_maker() as db:
                db.add(ChannelLog(task_id=task_id, channel_title="—", action="error", text=str(exc)))
                await db.commit()

        # Random variation ±40% so timing is never predictable
        # But wake up early if manually triggered
        base = check_interval * 60
        sleep_time = random.uniform(base * 0.6, base * 1.4)
        event = _triggers.setdefault(task_id, asyncio.Event())
        event.clear()
        try:
            await asyncio.wait_for(event.wait(), timeout=sleep_time)
        except asyncio.TimeoutError:
            pass

    logger.info("Channel task %d stopped", task_id)


async def _find_and_subscribe(client, task_id: int, keyword: str, max_channels: int, existing_subs) -> None:
    from telethon.tl.functions.contacts import SearchRequest
    from telethon.tl.functions.channels import JoinChannelRequest

    existing_ids = {s.channel_id for s in existing_subs}
    needed = max_channels - len(existing_subs)
    if needed <= 0:
        return

    try:
        result = await client(SearchRequest(q=keyword, limit=25))
        candidates = [
            c for c in result.chats
            if getattr(c, "broadcast", False)
            and not getattr(c, "restricted", False)
            and c.id not in existing_ids
        ]
        random.shuffle(candidates)

        joined = 0
        for channel in candidates:
            if joined >= needed:
                break
            try:
                await client(JoinChannelRequest(channel))
                async with async_session_maker() as db:
                    sub = ChannelSubscription(
                        task_id=task_id,
                        channel_id=channel.id,
                        channel_username=getattr(channel, "username", None),
                        channel_title=channel.title,
                    )
                    db.add(sub)
                    db.add(ChannelLog(
                        task_id=task_id,
                        channel_title=channel.title,
                        action="subscribed",
                        text=f"Подписался по запросу: {keyword}",
                    ))
                    await db.commit()
                joined += 1
                logger.info("Task %d subscribed to %s", task_id, channel.title)
                # Human-like pause between subscriptions (1-5 min)
                await asyncio.sleep(random.uniform(60, 5 * 60))
            except Exception as e:
                logger.warning("Task %d: failed to join %s: %s", task_id, channel.title, e)
    except Exception as e:
        logger.error("Task %d: channel search failed: %s", task_id, e)


async def _process_channel(client, task, sub: ChannelSubscription, generate_comment_fn) -> int:
    from telethon.tl.functions.channels import GetFullChannelRequest
    from telethon.tl.functions.messages import SendReactionRequest
    from telethon.tl.types import ReactionEmoji

    actions_taken = 0

    try:
        # Resolve entity: prefer username, fall back to dialog cache refresh
        try:
            identifier = f"@{sub.channel_username}" if sub.channel_username else sub.channel_id
            channel = await client.get_entity(identifier)
        except Exception:
            # Refresh dialog cache so Telethon learns access hashes, then retry
            await client.get_dialogs(limit=200)
            channel = await client.get_entity(sub.channel_id)

        new_posts = []
        async for msg in client.iter_messages(channel, limit=10, min_id=sub.last_post_id):
            if msg.text and len(msg.text) > 30:
                new_posts.append(msg)

        if not new_posts:
            return 0

        new_max_id = max(m.id for m in new_posts)
        post = random.choice(new_posts)

        # Simulate "reading" the post (15-90 sec, random)
        read_delay = random.uniform(15, 90)
        logger.info("Task %d: reading post in %s for %.0fs", task.id, sub.channel_title, read_delay)
        await asyncio.sleep(read_delay)

        # Maybe react
        react_roll = random.randint(1, 100)
        if react_roll <= task.reaction_probability:
            try:
                emoji = random.choice(REACTIONS)
                await client(SendReactionRequest(
                    peer=channel,
                    msg_id=post.id,
                    reaction=[ReactionEmoji(emoticon=emoji)],
                ))
                async with async_session_maker() as db:
                    db.add(ChannelLog(
                        task_id=task.id,
                        channel_title=sub.channel_title,
                        action="reacted",
                        text=f"{emoji} · {post.text[:120]}",
                    ))
                    await db.commit()
                actions_taken += 1
                logger.info("Task %d: reacted %s in %s", task.id, emoji, sub.channel_title)
                # Pause after reaction (30-180 sec)
                await asyncio.sleep(random.uniform(30, 180))
            except Exception as e:
                logger.warning("Task %d: react failed in %s: %s", task.id, sub.channel_title, e)
                async with async_session_maker() as db:
                    db.add(ChannelLog(task_id=task.id, channel_title=sub.channel_title, action="error", text=f"Реакция: {e}"))
                    await db.commit()
        else:
            logger.info("Task %d: skipped react in %s (roll %d > %d%%)", task.id, sub.channel_title, react_roll, task.reaction_probability)

        # Maybe comment
        comment_roll = random.randint(1, 100)
        has_replies = getattr(post, "replies", None)
        if comment_roll <= task.comment_probability:
            if not has_replies:
                logger.info("Task %d: skipped comment in %s (no discussion group)", task.id, sub.channel_title)
            else:
                try:
                    full = await client(GetFullChannelRequest(channel))
                    linked_id = full.full_chat.linked_chat_id
                    if linked_id:
                        # "Think" before writing (60-300 sec)
                        think_delay = random.uniform(60, 300)
                        logger.info("Task %d: thinking for %.0fs before commenting in %s", task.id, think_delay, sub.channel_title)
                        await asyncio.sleep(think_delay)
                        comment = await generate_comment_fn(post.text, task.persona)
                        await client.send_message(linked_id, comment, comment_to=post.id)
                        async with async_session_maker() as db:
                            db.add(ChannelLog(
                                task_id=task.id,
                                channel_title=sub.channel_title,
                                action="commented",
                                text=comment,
                            ))
                            await db.commit()
                        actions_taken += 1
                        logger.info("Task %d: commented in %s", task.id, sub.channel_title)
                    else:
                        logger.info("Task %d: skipped comment in %s (linked_chat_id=None)", task.id, sub.channel_title)
                except Exception as e:
                    logger.warning("Task %d: comment failed in %s: %s", task.id, sub.channel_title, e)
                    async with async_session_maker() as db:
                        db.add(ChannelLog(task_id=task.id, channel_title=sub.channel_title, action="error", text=f"Комментарий: {e}"))
                        await db.commit()
        else:
            logger.info("Task %d: skipped comment in %s (roll %d > %d%%)", task.id, sub.channel_title, comment_roll, task.comment_probability)

        # Update last seen post id
        async with async_session_maker() as db:
            s = await db.get(ChannelSubscription, sub.id)
            if s:
                s.last_post_id = new_max_id
                s.last_checked_at = datetime.utcnow()
            await db.commit()

    except Exception as e:
        logger.error("Task %d: processing %s failed: %s", task.id, sub.channel_title, e)

    return actions_taken
