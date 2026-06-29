from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from pydantic import BaseModel
from src.database import get_session
from src.models import (
    Account, WarmupTask, WarmupLog, WarmupStatus, AccountEvent
)
from src.services import warmup_service
from src.services.profile_service import setup_profile

router = APIRouter(prefix="/warmup", tags=["warmup"])


class StartWarmupRequest(BaseModel):
    account_id: int
    target_days: int = 7


class WarmupTaskOut(BaseModel):
    id: int
    account_id: int
    account_label: str | None
    account_phone: str | None
    status: WarmupStatus
    target_days: int
    current_day: int
    actions_today: int
    actions_total: int
    started_at: str | None
    completed_at: str | None
    last_activity_at: str | None
    created_at: str


class WarmupLogOut(BaseModel):
    id: int
    account_id: int
    action: str
    detail: str | None
    created_at: str


class AccountEventOut(BaseModel):
    id: int
    account_id: int
    event_type: str
    detail: str | None
    detected_at: str


class AccountStatsOut(BaseModel):
    id: int
    label: str
    phone: str
    status: str
    warmup_status: str
    warmup_started_at: str | None
    total_actions: int
    restrictions_count: int
    bans_count: int
    proxy: str | None
    created_at: str


class SetupProfileRequest(BaseModel):
    account_ids: list[int]
    gender: str = "random"
    set_photo: bool = True


def _task_out(task: WarmupTask, account: Account | None) -> WarmupTaskOut:
    return WarmupTaskOut(
        id=task.id,
        account_id=task.account_id,
        account_label=account.label if account else None,
        account_phone=account.phone if account else None,
        status=task.status,
        target_days=task.target_days,
        current_day=task.current_day or 0,
        actions_today=task.actions_today or 0,
        actions_total=task.actions_total or 0,
        started_at=task.started_at.isoformat() if task.started_at else None,
        completed_at=task.completed_at.isoformat() if task.completed_at else None,
        last_activity_at=task.last_activity_at.isoformat() if task.last_activity_at else None,
        created_at=task.created_at.isoformat(),
    )


@router.post("/start", response_model=WarmupTaskOut, status_code=201)
async def start_warmup(data: StartWarmupRequest, session: AsyncSession = Depends(get_session)):
    """Запустить прогрев для аккаунта."""
    if not (3 <= data.target_days <= 14):
        raise HTTPException(status_code=400, detail="target_days должно быть от 3 до 14")

    account = await session.get(Account, data.account_id)
    if not account or not account.is_active:
        raise HTTPException(status_code=404, detail="Аккаунт не найден")

    # Проверить: нет ли уже активной задачи
    existing = await session.execute(
        select(WarmupTask).where(
            WarmupTask.account_id == data.account_id,
            WarmupTask.status.in_([WarmupStatus.warming, WarmupStatus.pending]),
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Прогрев уже запущен для этого аккаунта")

    task = WarmupTask(
        account_id=data.account_id,
        status=WarmupStatus.warming,
        target_days=data.target_days,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)

    await warmup_service.start_warmup(task.id)

    return _task_out(task, account)


@router.post("/start-batch", status_code=200)
async def start_warmup_batch(
    data: StartWarmupRequest,
    account_ids: list[int],
    session: AsyncSession = Depends(get_session),
):
    """Запустить прогрев для нескольких аккаунтов сразу."""
    results = {"started": [], "skipped": [], "errors": []}

    for account_id in account_ids:
        account = await session.get(Account, account_id)
        if not account or not account.is_active:
            results["errors"].append({"id": account_id, "error": "Аккаунт не найден"})
            continue

        existing = await session.execute(
            select(WarmupTask).where(
                WarmupTask.account_id == account_id,
                WarmupTask.status.in_([WarmupStatus.warming, WarmupStatus.pending]),
            )
        )
        if existing.scalar_one_or_none():
            results["skipped"].append(account_id)
            continue

        task = WarmupTask(
            account_id=account_id,
            status=WarmupStatus.warming,
            target_days=data.target_days,
        )
        session.add(task)
        await session.flush()
        await session.refresh(task)
        await warmup_service.start_warmup(task.id)
        results["started"].append(account_id)

    await session.commit()
    return results


@router.get("/tasks", response_model=list[WarmupTaskOut])
async def list_warmup_tasks(session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(WarmupTask).order_by(desc(WarmupTask.created_at))
    )
    tasks = result.scalars().all()
    out = []
    for task in tasks:
        account = await session.get(Account, task.account_id)
        out.append(_task_out(task, account))
    return out


@router.patch("/tasks/{task_id}/pause")
async def pause_warmup(task_id: int, session: AsyncSession = Depends(get_session)):
    task = await session.get(WarmupTask, task_id)
    if not task:
        raise HTTPException(status_code=404)
    task.status = WarmupStatus.paused
    await session.commit()
    return {"ok": True}


@router.patch("/tasks/{task_id}/resume")
async def resume_warmup(task_id: int, session: AsyncSession = Depends(get_session)):
    task = await session.get(WarmupTask, task_id)
    if not task:
        raise HTTPException(status_code=404)
    task.status = WarmupStatus.warming
    await session.commit()
    await warmup_service.start_warmup(task_id)
    return {"ok": True}


@router.delete("/tasks/{task_id}")
async def stop_warmup(task_id: int, session: AsyncSession = Depends(get_session)):
    task = await session.get(WarmupTask, task_id)
    if not task:
        raise HTTPException(status_code=404)
    await warmup_service.stop_warmup(task_id)
    task.status = WarmupStatus.failed
    await session.commit()
    return {"ok": True}


@router.get("/logs/{account_id}", response_model=list[WarmupLogOut])
async def get_warmup_logs(
    account_id: int,
    limit: int = 100,
    session: AsyncSession = Depends(get_session),
):
    limit = min(max(limit, 1), 500)
    result = await session.execute(
        select(WarmupLog)
        .where(WarmupLog.account_id == account_id)
        .order_by(desc(WarmupLog.created_at))
        .limit(limit)
    )
    return [
        WarmupLogOut(
            id=l.id, account_id=l.account_id,
            action=l.action, detail=l.detail,
            created_at=l.created_at.isoformat(),
        )
        for l in result.scalars().all()
    ]


# ── Мониторинг аккаунтов ──────────────────────────────────────────────────────

@router.get("/stats", response_model=list[AccountStatsOut])
async def get_account_stats(session: AsyncSession = Depends(get_session)):
    """Статистика по всем аккаунтам: действия, ограничения, баны."""
    result = await session.execute(
        select(Account).where(Account.is_active == True)
    )
    accounts = result.scalars().all()
    return [
        AccountStatsOut(
            id=a.id,
            label=a.label,
            phone=a.phone,
            status=a.status,
            warmup_status=a.warmup_status or "none",
            warmup_started_at=a.warmup_started_at.isoformat() if a.warmup_started_at else None,
            total_actions=a.total_actions or 0,
            restrictions_count=a.restrictions_count or 0,
            bans_count=a.bans_count or 0,
            proxy=a.proxy,
            created_at=a.created_at.isoformat(),
        )
        for a in accounts
    ]


@router.get("/events", response_model=list[AccountEventOut])
async def get_account_events(limit: int = 200, session: AsyncSession = Depends(get_session)):
    """Все события: баны, ограничения, флуд-вейты."""
    limit = min(max(limit, 1), 500)
    result = await session.execute(
        select(AccountEvent).order_by(desc(AccountEvent.detected_at)).limit(limit)
    )
    return [
        AccountEventOut(
            id=e.id, account_id=e.account_id,
            event_type=e.event_type, detail=e.detail,
            detected_at=e.detected_at.isoformat(),
        )
        for e in result.scalars().all()
    ]


# ── Автонастройка профилей ────────────────────────────────────────────────────

@router.post("/setup-profiles")
async def setup_profiles(data: SetupProfileRequest, session: AsyncSession = Depends(get_session)):
    """Автонастройка профилей: имя, username, bio, аватарка."""
    results = []
    for account_id in data.account_ids[:50]:  # макс 50 за раз
        account = await session.get(Account, account_id)
        if not account or not account.is_active:
            results.append({"account_id": account_id, "error": "Не найден"})
            continue
        result = await setup_profile(
            account_id=account_id,
            session_string=account.session_string,
            proxy=account.proxy,
            gender=data.gender,
            set_photo=data.set_photo,
        )
        results.append(result)
    return results
