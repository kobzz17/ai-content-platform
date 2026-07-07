import re
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from pydantic import BaseModel
from src.database import get_session
from src.models import BotTask, BotLog, TaskStatus, Account, BoostTask, BoostLog, BoostStatus
from src.services import bot_service, boost_service
import src.session_manager as sm

router = APIRouter(prefix="/automation", tags=["automation"])


class CreateTaskRequest(BaseModel):
    account_id: int
    chat_id: int
    chat_name: str
    persona: str = "Дружелюбный человек, любящий поддерживать разговор"
    reply_probability: int = 70
    min_delay: int = 5
    max_delay: int = 30
    proactive_interval: int | None = None

    from pydantic import model_validator, field_validator

    @field_validator("reply_probability")
    @classmethod
    def _prob_range(cls, v: int) -> int:
        if not (0 <= v <= 100):
            raise ValueError("Должно быть от 0 до 100")
        return v

    @field_validator("min_delay", "max_delay")
    @classmethod
    def _delay_range(cls, v: int) -> int:
        if not (0 <= v <= 3600):
            raise ValueError("Задержка должна быть от 0 до 3600 секунд")
        return v

    @model_validator(mode="after")
    def _delay_order(self) -> "CreateTaskRequest":
        if self.min_delay > self.max_delay:
            raise ValueError("min_delay не может быть больше max_delay")
        return self


class UpdateStatusRequest(BaseModel):
    status: TaskStatus


class TaskOut(BaseModel):
    id: int
    account_id: int
    account_label: str | None
    chat_id: int
    chat_name: str
    status: TaskStatus
    persona: str
    reply_probability: int
    min_delay: int
    max_delay: int
    proactive_interval: int | None
    last_action_at: str | None
    created_at: str


class LogOut(BaseModel):
    id: int
    task_id: int
    action: str
    text: str | None
    created_at: str


def _task_out(task: BotTask, label: str | None) -> TaskOut:
    return TaskOut(
        id=task.id,
        account_id=task.account_id,
        account_label=label,
        chat_id=task.chat_id,
        chat_name=task.chat_name,
        status=task.status,
        persona=task.persona,
        reply_probability=task.reply_probability,
        min_delay=task.min_delay,
        max_delay=task.max_delay,
        proactive_interval=task.proactive_interval,
        last_action_at=task.last_action_at.isoformat() if task.last_action_at else None,
        created_at=task.created_at.isoformat(),
    )


def _log_out(log: BotLog) -> LogOut:
    return LogOut(
        id=log.id,
        task_id=log.task_id,
        action=log.action,
        text=log.text,
        created_at=log.created_at.isoformat(),
    )


@router.post("/tasks", response_model=TaskOut, status_code=201)
async def create_task(data: CreateTaskRequest, session: AsyncSession = Depends(get_session)):
    account = await session.get(Account, data.account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    task = BotTask(
        account_id=data.account_id,
        chat_id=data.chat_id,
        chat_name=data.chat_name,
        persona=data.persona,
        reply_probability=data.reply_probability,
        min_delay=data.min_delay,
        max_delay=data.max_delay,
        proactive_interval=data.proactive_interval,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    await bot_service.start_task(task.id)
    return _task_out(task, account.label)


@router.get("/tasks", response_model=list[TaskOut])
async def list_tasks(session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(BotTask)
        .where(BotTask.status != TaskStatus.stopped)
        .order_by(desc(BotTask.created_at))
    )
    tasks = result.scalars().all()
    out = []
    for task in tasks:
        account = await session.get(Account, task.account_id)
        out.append(_task_out(task, account.label if account else None))
    return out


@router.patch("/tasks/{task_id}", response_model=TaskOut)
async def update_task_status(
    task_id: int,
    data: UpdateStatusRequest,
    session: AsyncSession = Depends(get_session),
):
    task = await session.get(BotTask, task_id)
    if not task:
        raise HTTPException(status_code=404)

    if data.status == TaskStatus.stopped:
        await bot_service.stop_task(task_id)
    elif data.status == TaskStatus.running and task.status == TaskStatus.paused:
        await bot_service.start_task(task_id)

    task.status = data.status
    await session.commit()
    await session.refresh(task)

    account = await session.get(Account, task.account_id)
    return _task_out(task, account.label if account else None)


@router.get("/tasks/{task_id}/logs", response_model=list[LogOut])
async def get_task_logs(task_id: int, limit: int = 50, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(BotLog)
        .where(BotLog.task_id == task_id)
        .order_by(desc(BotLog.created_at))
        .limit(limit)
    )
    return [_log_out(log) for log in result.scalars().all()]


@router.get("/logs", response_model=list[LogOut])
async def get_all_logs(limit: int = 100, session: AsyncSession = Depends(get_session)):
    limit = min(max(limit, 1), 500)
    result = await session.execute(
        select(BotLog).order_by(desc(BotLog.created_at)).limit(limit)
    )
    return [_log_out(log) for log in result.scalars().all()]


# ── Boost endpoints ───────────────────────────────────────────────────────────

class CreateBoostRequest(BaseModel):
    message_link: str   # t.me/c/CHATID/MSGID URL or plain message ID number
    topic: str | None = None
    duration_minutes: int = 60


class BoostOut(BaseModel):
    id: int
    message_link: str
    chat_id: int
    message_id: int
    topic: str | None
    status: str
    duration_minutes: int
    total_accounts: int
    comments_posted: int
    created_at: str
    ends_at: str


class BoostLogOut(BaseModel):
    id: int
    boost_id: int
    account_id: int
    account_label: str | None
    action: str
    text: str | None
    created_at: str


def _boost_out(b: BoostTask) -> BoostOut:
    return BoostOut(
        id=b.id,
        message_link=b.message_link,
        chat_id=b.chat_id,
        message_id=b.message_id,
        topic=b.topic,
        status=b.status,
        duration_minutes=b.duration_minutes,
        total_accounts=b.total_accounts,
        comments_posted=b.comments_posted,
        created_at=b.created_at.isoformat(),
        ends_at=b.ends_at.isoformat(),
    )


def _extract_message_id(link_or_id: str) -> tuple[int | None, int]:
    """Return (raw_channel_id_or_None, message_id) from a t.me link or plain ID."""
    s = link_or_id.strip()
    if re.match(r'^\d+$', s):
        return None, int(s)
    m = re.match(r'https?://t\.me/c/(\d+)/(\d+)', s)
    if m:
        return int(m.group(1)), int(m.group(2))
    # Public username link: https://t.me/username/123
    m2 = re.search(r'/(\d+)$', s)
    if m2:
        return None, int(m2.group(1))
    raise ValueError("Введи ссылку на сообщение (t.me/c/...) или его ID (число)")


@router.post("/boost", response_model=BoostOut, status_code=201)
async def create_boost(data: CreateBoostRequest, session: AsyncSession = Depends(get_session)):
    try:
        raw_channel_id, message_id = _extract_message_id(data.message_link)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Find the matching chat_id from running BotTasks
    chat_id: int | None = None
    if raw_channel_id is not None:
        # Try both storage formats: -RAW and -(1e12+RAW)
        candidates = [-raw_channel_id, -(1_000_000_000_000 + raw_channel_id)]
        r = await session.execute(
            select(BotTask).where(
                BotTask.status == TaskStatus.running,
                BotTask.chat_id.in_(candidates),
            ).limit(1)
        )
        bt = r.scalars().first()
        if bt:
            chat_id = bt.chat_id

    if chat_id is None:
        # Fall back to the first running BotTask's chat
        r = await session.execute(
            select(BotTask).where(BotTask.status == TaskStatus.running).limit(1)
        )
        bt = r.scalars().first()
        if not bt:
            raise HTTPException(status_code=400, detail="Нет активных задач бота. Сначала запусти автоматизацию.")
        chat_id = bt.chat_id

    ends_at = datetime.utcnow() + timedelta(minutes=data.duration_minutes)
    boost = BoostTask(
        message_link=data.message_link,
        chat_id=chat_id,
        message_id=message_id,
        topic=data.topic or None,
        status=BoostStatus.running,
        duration_minutes=data.duration_minutes,
        ends_at=ends_at,
    )
    session.add(boost)
    await session.commit()
    await session.refresh(boost)

    await boost_service.start_boost(boost.id)
    return _boost_out(boost)


@router.get("/boosts", response_model=list[BoostOut])
async def list_boosts(session: AsyncSession = Depends(get_session)):
    r = await session.execute(
        select(BoostTask).order_by(desc(BoostTask.created_at)).limit(20)
    )
    return [_boost_out(b) for b in r.scalars().all()]


@router.delete("/boosts/{boost_id}", status_code=204)
async def cancel_boost(boost_id: int, session: AsyncSession = Depends(get_session)):
    boost = await session.get(BoostTask, boost_id)
    if not boost:
        raise HTTPException(status_code=404)
    await boost_service.stop_boost(boost_id)
    boost.status = BoostStatus.cancelled
    await session.commit()


@router.get("/boosts/{boost_id}/logs", response_model=list[BoostLogOut])
async def get_boost_logs(boost_id: int, session: AsyncSession = Depends(get_session)):
    r = await session.execute(
        select(BoostLog).where(BoostLog.boost_id == boost_id).order_by(BoostLog.created_at)
    )
    logs = r.scalars().all()
    out = []
    for log in logs:
        acc = await session.get(Account, log.account_id)
        out.append(BoostLogOut(
            id=log.id,
            boost_id=log.boost_id,
            account_id=log.account_id,
            account_label=acc.label if acc else None,
            action=log.action,
            text=log.text,
            created_at=log.created_at.isoformat(),
        ))
    return out


@router.get("/resolve-chat")
async def resolve_chat(
    identifier: str,
    account_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Resolve @username or invite link to numeric chat ID and name."""
    account = await session.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    try:
        client = await sm.get_client(account.id, account.session_string, account.proxy)
        entity = await client.get_entity(identifier)
        name = (
            getattr(entity, "title", None)
            or getattr(entity, "first_name", None)
            or identifier
        )
        return {"chat_id": entity.id, "name": name}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
