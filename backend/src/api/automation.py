from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from pydantic import BaseModel
from src.database import get_session
from src.models import BotTask, BotLog, TaskStatus, Account
from src.services import bot_service
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
