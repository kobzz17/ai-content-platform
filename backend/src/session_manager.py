"""
Manages Telethon client instances for multiple Telegram accounts.
One TelegramClient per account, kept alive in memory.
"""
import asyncio
import logging
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import User
from src.config import settings

logger = logging.getLogger(__name__)

# account_id → active TelegramClient
_clients: dict[int, TelegramClient] = {}
# phone → temp client during auth flow
_auth_clients: dict[str, TelegramClient] = {}
# phone → phone_code_hash during auth
_auth_hashes: dict[str, str] = {}


def _make_client(session_string: str = "", proxy: str | None = None) -> TelegramClient:
    proxy_params = _parse_proxy(proxy) if proxy else None
    return TelegramClient(
        StringSession(session_string),
        settings.telegram_api_id,
        settings.telegram_api_hash,
        proxy=proxy_params,
    )


def _parse_proxy(proxy_url: str) -> tuple | None:
    """Parse socks5://user:pass@host:port into Telethon proxy tuple."""
    try:
        from urllib.parse import urlparse
        import socks
        p = urlparse(proxy_url)
        return (socks.SOCKS5, p.hostname, p.port, True, p.username, p.password)
    except Exception:
        return None


async def get_client(account_id: int, session_string: str, proxy: str | None = None) -> TelegramClient:
    if account_id not in _clients:
        client = _make_client(session_string, proxy)
        await client.connect()
        if not await client.is_user_authorized():
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

async def start_auth(phone: str) -> None:
    """Step 1: send code to phone number."""
    client = _make_client()
    await client.connect()
    result = await client.send_code_request(phone)
    _auth_clients[phone] = client
    _auth_hashes[phone] = result.phone_code_hash
    logger.info("Auth code sent to %s", phone)


async def complete_auth(phone: str, code: str, password: str | None = None) -> tuple[str, User]:
    """Step 2: confirm code (+ 2FA password if set). Returns (session_string, me)."""
    client = _auth_clients.get(phone)
    if not client:
        raise ValueError("No pending auth for this phone. Call start_auth first.")
    phone_code_hash = _auth_hashes[phone]

    try:
        await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
    except Exception as e:
        if "SessionPasswordNeeded" in type(e).__name__:
            if not password:
                raise ValueError("2FA password required") from e
            await client.sign_in(password=password)
        else:
            raise

    me = await client.get_me()
    session_string = client.session.save()

    # Clean up temp auth state
    _auth_clients.pop(phone, None)
    _auth_hashes.pop(phone, None)

    return session_string, me
