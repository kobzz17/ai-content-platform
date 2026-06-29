from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from src.database import get_session
from src.models import Proxy, Account

router = APIRouter(prefix="/proxies", tags=["proxies"])


class AddProxyRequest(BaseModel):
    protocol: str = "socks5"
    host: str
    port: int
    username: str | None = None
    password: str | None = None


class AddProxyBatchRequest(BaseModel):
    proxies: list[str]  # формат: protocol://user:pass@host:port  или  host:port


class ProxyOut(BaseModel):
    id: int
    protocol: str
    host: str
    port: int
    username: str | None
    is_active: bool
    is_healthy: bool
    last_checked_at: str | None
    assigned_account_id: int | None
    assigned_account_label: str | None
    added_at: str


class AssignProxyRequest(BaseModel):
    account_id: int


def _parse_proxy_string(s: str) -> dict | None:
    """Разобрать строку вида socks5://user:pass@host:port или host:port."""
    s = s.strip()
    if not s:
        return None
    try:
        # С протоколом
        if "://" in s:
            from urllib.parse import urlparse
            p = urlparse(s)
            return {
                "protocol": p.scheme or "socks5",
                "host": p.hostname,
                "port": p.port or 1080,
                "username": p.username,
                "password": p.password,
            }
        # Без протокола: host:port или user:pass@host:port
        if "@" in s:
            creds, hostport = s.rsplit("@", 1)
            user, pwd = creds.split(":", 1) if ":" in creds else (creds, None)
        else:
            creds, hostport = None, s
            user = pwd = None
        host, port_str = hostport.rsplit(":", 1)
        return {
            "protocol": "socks5",
            "host": host,
            "port": int(port_str),
            "username": user,
            "password": pwd,
        }
    except Exception:
        return None


def _proxy_out(proxy: Proxy, account_label: str | None = None) -> ProxyOut:
    return ProxyOut(
        id=proxy.id,
        protocol=proxy.protocol,
        host=proxy.host,
        port=proxy.port,
        username=proxy.username,
        is_active=proxy.is_active,
        is_healthy=proxy.is_healthy,
        last_checked_at=proxy.last_checked_at.isoformat() if proxy.last_checked_at else None,
        assigned_account_id=proxy.assigned_account_id,
        assigned_account_label=account_label,
        added_at=proxy.added_at.isoformat(),
    )


@router.get("/", response_model=list[ProxyOut])
async def list_proxies(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Proxy).where(Proxy.is_active == True))
    proxies = result.scalars().all()
    out = []
    for p in proxies:
        label = None
        if p.assigned_account_id:
            acc = await session.get(Account, p.assigned_account_id)
            label = acc.label if acc else None
        out.append(_proxy_out(p, label))
    return out


@router.post("/", response_model=ProxyOut, status_code=201)
async def add_proxy(data: AddProxyRequest, session: AsyncSession = Depends(get_session)):
    proxy = Proxy(
        protocol=data.protocol,
        host=data.host,
        port=data.port,
        username=data.username,
        password=data.password,
    )
    session.add(proxy)
    await session.commit()
    await session.refresh(proxy)
    return _proxy_out(proxy)


@router.post("/batch", status_code=200)
async def add_proxies_batch(data: AddProxyBatchRequest, session: AsyncSession = Depends(get_session)):
    """Массовое добавление прокси, по одной строке на прокси."""
    added = 0
    failed = []
    for line in data.proxies:
        parsed = _parse_proxy_string(line)
        if not parsed:
            failed.append({"line": line, "error": "Не удалось разобрать строку"})
            continue
        proxy = Proxy(**parsed)
        session.add(proxy)
        added += 1
    await session.commit()
    return {"added": added, "failed": failed}


@router.post("/{proxy_id}/assign", response_model=ProxyOut)
async def assign_proxy(
    proxy_id: int,
    data: AssignProxyRequest,
    session: AsyncSession = Depends(get_session),
):
    """Назначить прокси аккаунту и записать socks5://... в account.proxy."""
    proxy = await session.get(Proxy, proxy_id)
    if not proxy:
        raise HTTPException(status_code=404, detail="Прокси не найден")

    account = await session.get(Account, data.account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Аккаунт не найден")

    # Снять старый прокси с этого аккаунта
    old = await session.execute(
        select(Proxy).where(Proxy.assigned_account_id == data.account_id)
    )
    for old_p in old.scalars().all():
        if old_p.id != proxy_id:
            old_p.assigned_account_id = None

    proxy.assigned_account_id = data.account_id

    # Записать строку подключения в account.proxy
    creds = f"{proxy.username}:{proxy.password}@" if proxy.username else ""
    account.proxy = f"{proxy.protocol}://{creds}{proxy.host}:{proxy.port}"

    await session.commit()
    await session.refresh(proxy)
    return _proxy_out(proxy, account.label)


@router.post("/auto-assign")
async def auto_assign_proxies(session: AsyncSession = Depends(get_session)):
    """Автоматически распределить свободные прокси по аккаунтам без прокси."""
    free_proxies = await session.execute(
        select(Proxy).where(
            Proxy.is_active == True,
            Proxy.assigned_account_id == None,
        )
    )
    proxies = list(free_proxies.scalars().all())

    accounts_without_proxy = await session.execute(
        select(Account).where(
            Account.is_active == True,
            Account.proxy == None,
        )
    )
    accounts = list(accounts_without_proxy.scalars().all())

    assigned = 0
    for account, proxy in zip(accounts, proxies):
        proxy.assigned_account_id = account.id
        creds = f"{proxy.username}:{proxy.password}@" if proxy.username else ""
        account.proxy = f"{proxy.protocol}://{creds}{proxy.host}:{proxy.port}"
        assigned += 1

    await session.commit()
    return {
        "assigned": assigned,
        "accounts_without_proxy": len(accounts) - assigned,
        "proxies_remaining": len(proxies) - assigned,
    }


@router.post("/{proxy_id}/check")
async def check_proxy(proxy_id: int, session: AsyncSession = Depends(get_session)):
    """Проверить работоспособность прокси (тест подключения к Telegram)."""
    import httpx
    from datetime import datetime

    proxy = await session.get(Proxy, proxy_id)
    if not proxy:
        raise HTTPException(status_code=404)

    creds = f"{proxy.username}:{proxy.password}@" if proxy.username else ""
    proxy_url = f"{proxy.protocol}://{creds}{proxy.host}:{proxy.port}"

    is_healthy = False
    error = None
    try:
        async with httpx.AsyncClient(proxy=proxy_url, timeout=10) as client:
            r = await client.get("https://api.telegram.org")
            is_healthy = r.status_code < 500
    except Exception as e:
        error = str(e)[:200]

    proxy.is_healthy = is_healthy
    proxy.last_checked_at = datetime.utcnow()
    await session.commit()

    return {"healthy": is_healthy, "error": error}


@router.delete("/{proxy_id}", status_code=204)
async def delete_proxy(proxy_id: int, session: AsyncSession = Depends(get_session)):
    proxy = await session.get(Proxy, proxy_id)
    if not proxy:
        raise HTTPException(status_code=404)
    # Снять с аккаунта если был назначен
    if proxy.assigned_account_id:
        acc = await session.get(Account, proxy.assigned_account_id)
        if acc:
            acc.proxy = None
    proxy.is_active = False
    await session.commit()
