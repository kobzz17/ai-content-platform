from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from pydantic import BaseModel
from src.database import get_session
from src.models import ChannelTask, ChannelSubscription, ChannelLog, TaskStatus, SessionMode, Account
from src.services import channel_service

router = APIRouter(prefix="/channels", tags=["channels"])


class CreateChannelTaskRequest(BaseModel):
    account_id: int
    keywords: str
    persona: str = "Интересующийся IT-новостями читатель, любит делиться мнением"
    max_channels: int = 5
    comment_probability: int = 40
    reaction_probability: int = 60
    check_interval: int = 60
    max_daily_actions: int = 15
    session_mode: SessionMode = SessionMode.always

    from pydantic import field_validator

    @field_validator("comment_probability", "reaction_probability")
    @classmethod
    def _prob_range(cls, v: int) -> int:
        if not (0 <= v <= 100):
            raise ValueError("Должно быть от 0 до 100")
        return v

    @field_validator("max_channels")
    @classmethod
    def _max_channels_range(cls, v: int) -> int:
        if not (1 <= v <= 50):
            raise ValueError("Должно быть от 1 до 50")
        return v

    @field_validator("check_interval")
    @classmethod
    def _interval_range(cls, v: int) -> int:
        if not (1 <= v <= 1440):
            raise ValueError("Должно быть от 1 до 1440 минут")
        return v

    @field_validator("max_daily_actions")
    @classmethod
    def _daily_range(cls, v: int) -> int:
        if not (1 <= v <= 200):
            raise ValueError("Должно быть от 1 до 200")
        return v


class UpdateStatusRequest(BaseModel):
    status: TaskStatus


class ChannelTaskOut(BaseModel):
    id: int
    account_id: int
    account_label: str | None
    keywords: str
    status: TaskStatus
    persona: str
    max_channels: int
    comment_probability: int
    reaction_probability: int
    check_interval: int
    max_daily_actions: int
    session_mode: str
    offline_until: str | None
    subscriptions_count: int = 0
    last_run_at: str | None
    created_at: str


class SubscriptionOut(BaseModel):
    id: int
    channel_title: str
    channel_username: str | None
    last_checked_at: str | None
    subscribed_at: str


class ChannelLogOut(BaseModel):
    id: int
    task_id: int
    channel_title: str
    action: str
    text: str | None
    created_at: str


def _task_out(task: ChannelTask, label: str | None, subs_count: int = 0) -> ChannelTaskOut:
    return ChannelTaskOut(
        id=task.id,
        account_id=task.account_id,
        account_label=label,
        keywords=task.keywords,
        status=task.status,
        persona=task.persona,
        max_channels=task.max_channels,
        comment_probability=task.comment_probability,
        reaction_probability=task.reaction_probability,
        check_interval=task.check_interval,
        max_daily_actions=task.max_daily_actions,
        session_mode=task.session_mode or "always",
        offline_until=task.offline_until.isoformat() if task.offline_until else None,
        subscriptions_count=subs_count,
        last_run_at=task.last_run_at.isoformat() if task.last_run_at else None,
        created_at=task.created_at.isoformat(),
    )


@router.post("/tasks", response_model=ChannelTaskOut, status_code=201)
async def create_task(data: CreateChannelTaskRequest, session: AsyncSession = Depends(get_session)):
    account = await session.get(Account, data.account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    task = ChannelTask(
        account_id=data.account_id,
        keywords=data.keywords,
        persona=data.persona,
        max_channels=data.max_channels,
        comment_probability=data.comment_probability,
        reaction_probability=data.reaction_probability,
        check_interval=data.check_interval,
        max_daily_actions=data.max_daily_actions,
        session_mode=data.session_mode,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    await channel_service.start_task(task.id)
    return _task_out(task, account.label)


@router.get("/tasks", response_model=list[ChannelTaskOut])
async def list_tasks(session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(ChannelTask)
        .where(ChannelTask.status != TaskStatus.stopped)
        .order_by(desc(ChannelTask.created_at))
    )
    tasks = result.scalars().all()
    out = []
    for task in tasks:
        account = await session.get(Account, task.account_id)
        subs = await session.execute(
            select(ChannelSubscription).where(ChannelSubscription.task_id == task.id)
        )
        out.append(_task_out(task, account.label if account else None, len(subs.scalars().all())))
    return out


@router.patch("/tasks/{task_id}", response_model=ChannelTaskOut)
async def update_task_status(task_id: int, data: UpdateStatusRequest, session: AsyncSession = Depends(get_session)):
    task = await session.get(ChannelTask, task_id)
    if not task:
        raise HTTPException(status_code=404)

    if data.status == TaskStatus.stopped:
        await channel_service.stop_task(task_id)
    elif data.status == TaskStatus.running and task.status == TaskStatus.paused:
        await channel_service.start_task(task_id)

    task.status = data.status
    await session.commit()
    await session.refresh(task)

    account = await session.get(Account, task.account_id)
    subs = await session.execute(
        select(ChannelSubscription).where(ChannelSubscription.task_id == task_id)
    )
    return _task_out(task, account.label if account else None, len(subs.scalars().all()))


@router.get("/tasks/{task_id}/subscriptions", response_model=list[SubscriptionOut])
async def get_subscriptions(task_id: int, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(ChannelSubscription).where(ChannelSubscription.task_id == task_id)
    )
    return [
        SubscriptionOut(
            id=s.id,
            channel_title=s.channel_title,
            channel_username=s.channel_username,
            last_checked_at=s.last_checked_at.isoformat() if s.last_checked_at else None,
            subscribed_at=s.subscribed_at.isoformat(),
        )
        for s in result.scalars().all()
    ]


@router.post("/tasks/{task_id}/trigger", status_code=200)
async def trigger_task(task_id: int, session: AsyncSession = Depends(get_session)):
    """Wake up a sleeping task to run one iteration immediately."""
    task = await session.get(ChannelTask, task_id)
    if not task:
        raise HTTPException(status_code=404)
    if task.status != TaskStatus.running:
        raise HTTPException(status_code=400, detail="Task is not running")
    await channel_service.trigger_now(task_id)
    # If not in memory (e.g. after restart without status change), start it
    await channel_service.start_task(task_id)
    return {"ok": True}


@router.get("/logs", response_model=list[ChannelLogOut])
async def get_all_logs(limit: int = 100, session: AsyncSession = Depends(get_session)):
    limit = min(max(limit, 1), 500)
    result = await session.execute(
        select(ChannelLog).order_by(desc(ChannelLog.created_at)).limit(limit)
    )
    return [
        ChannelLogOut(
            id=l.id, task_id=l.task_id, channel_title=l.channel_title,
            action=l.action, text=l.text, created_at=l.created_at.isoformat()
        )
        for l in result.scalars().all()
    ]
