"""
Manages Telethon client instances for multiple Telegram accounts.
One TelegramClient per account, kept alive in memory.
"""
import asyncio
import logging
import time
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.network.connection.tcpobfuscated import ConnectionTcpObfuscated
from telethon.tl.types import User
from src.config import settings

logger = logging.getLogger(__name__)

# account_id → active TelegramClient
_clients: dict[int, TelegramClient] = {}
# per-account lock to prevent concurrent connect() for the same account_id
_connect_locks: dict[int, asyncio.Lock] = {}
# phone → temp client during auth flow
_auth_clients: dict[str, TelegramClient] = {}
# phone → phone_code_hash during auth
_auth_hashes: dict[str, str] = {}
# phone → timestamp when auth was started (for cleanup)
_auth_started: dict[str, float] = {}

_AUTH_TIMEOUT_SEC = 600  # auth sessions expire after 10 minutes


def _make_client(session_string: str = "", proxy: str | None = None) -> TelegramClient:
    proxy_params = _parse_proxy(proxy) if proxy else None
    return TelegramClient(
        StringSession(session_string),
        settings.telegram_api_id,
        settings.telegram_api_hash,
        connection=ConnectionTcpObfuscated,
        proxy=proxy_params,
        timeout=30,
        connection_retries=3,
    )


def _parse_proxy(proxy_url: str) -> tuple | None:
    """Parse socks5://user:pass@host:port into Telethon proxy tuple."""
    try:
        from urllib.parse import urlparse
        p = urlparse(proxy_url)
        scheme = p.scheme  # 'socks5', 'socks4', 'http'
        if p.username:
            return (scheme, p.hostname, p.port, True, p.username, p.password)
        return (scheme, p.hostname, p.port)
    except Exception:
        return None


async def get_client(account_id: int, session_string: str, proxy: str | None = None) -> TelegramClient:
    if account_id in _clients:
        return _clients[account_id]
    # Per-account lock prevents two concurrent callers from both creating a client
    lock = _connect_locks.setdefault(account_id, asyncio.Lock())
    async with lock:
        if account_id in _clients:  # double-check after acquiring lock
            return _clients[account_id]
        client = _make_client(session_string, proxy)
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            raise RuntimeError(f"Account {account_id} session expired, needs re-auth")
        _clients[account_id] = client
        logger.info("Connected account %d", account_id)
    return _clients[account_id]


async def disconnect_client(account_id: int):
    client = _clients.pop(account_id, None)
    if client:
        await client.disconnect()


async def disconnect_all():
    for client in _clients.values():
        await client.disconnect()
    _clients.clear()


# ── Auth flow ──────────────────────────────────────────────────────────────

async def _cleanup_expired_auth() -> None:
    """Disconnect and remove auth sessions older than _AUTH_TIMEOUT_SEC."""
    now = time.monotonic()
    expired = [p for p, t in _auth_started.items() if now - t > _AUTH_TIMEOUT_SEC]
    for phone in expired:
        client = _auth_clients.pop(phone, None)
        _auth_hashes.pop(phone, None)
        _auth_started.pop(phone, None)
        if client:
            try:
                await client.disconnect()
            except Exception:
                pass
        logger.info("Cleaned up expired auth session for %s", phone)


async def start_auth(phone: str, proxy: str | None = None) -> None:
    """Step 1: send code to phone number."""
    await _cleanup_expired_auth()
    # Disconnect previous pending auth for this phone if any
    old = _auth_clients.pop(phone, None)
    if old:
        try:
            await old.disconnect()
        except Exception:
            pass
    client = _make_client(proxy=proxy)
    await client.connect()
    result = await client.send_code_request(phone)
    _auth_clients[phone] = client
    _auth_hashes[phone] = result.phone_code_hash
    _auth_started[phone] = time.monotonic()
    logger.info("Auth code sent to %s", phone)


async def complete_auth(phone: str, code: str, password: str | None = None, first_name: str | None = None) -> tuple[str, User]:
    """Step 2: confirm code (+ 2FA password if set). Returns (session_string, me)."""
    client = _auth_clients.get(phone)
    if not client:
        raise ValueError("No pending auth for this phone. Call start_auth first.")
    phone_code_hash = _auth_hashes[phone]

    try:
        await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
    except Exception as e:
        ename = type(e).__name__
        if "SessionPasswordNeeded" in ename:
            if not password:
                raise ValueError("2FA password required") from e
            await client.sign_in(password=password)
        elif "PhoneNumberUnregistered" in ename:
            # New number — register it on Telegram
            await client.sign_up(code, first_name or "User", phone_code_hash=phone_code_hash)
        else:
            raise

    me = await client.get_me()
    session_string = client.session.save()

    # Clean up temp auth state
    _auth_clients.pop(phone, None)
    _auth_hashes.pop(phone, None)
    _auth_started.pop(phone, None)

    return session_string, me
