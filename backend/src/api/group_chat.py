import json
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from pydantic import BaseModel
from src.database import get_session
from src.models import Account, GroupChatSession, GroupChatLog
from src.services import group_chat_service
import src.session_manager as sm

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/group-chat", tags=["group-chat"])


class JoinAndStartRequest(BaseModel):
    invite_link: str          # https://t.me/+HASH или просто HASH
    account_ids: list[int]
    duration_days: int = 2


class GroupChatSessionOut(BaseModel):
    id: int
    chat_id: int
    chat_title: str
    account_ids: list[int]
    status: str
    duration_days: int
    started_at: str | None
    created_at: str


def _out(s: GroupChatSession) -> GroupChatSessionOut:
    return GroupChatSessionOut(
        id=s.id,
        chat_id=s.chat_id,
        chat_title=s.chat_title,
        account_ids=json.loads(s.account_ids),
        status=s.status,
        duration_days=s.duration_days,
        started_at=s.started_at.isoformat() if s.started_at else None,
        created_at=s.created_at.isoformat(),
    )


def _extract_hash(invite_link: str) -> str:
    """Извлечь хэш из https://t.me/+HASH или вернуть как есть."""
    link = invite_link.strip()
    if "t.me/+" in link:
        return link.split("t.me/+")[-1].split("/")[0].split("?")[0]
    if "t.me/joinchat/" in link:
        return link.split("t.me/joinchat/")[-1].split("/")[0].split("?")[0]
    return link


@router.post("/join-and-start", response_model=GroupChatSessionOut, status_code=201)
async def join_and_start(data: JoinAndStartRequest, session: AsyncSession = Depends(get_session)):
    """
    1. Все указанные аккаунты вступают в группу по invite-ссылке.
    2. Запускается сессия группового чата.
    """
    from telethon.tl.functions.messages import ImportChatInviteRequest, CheckChatInviteRequest
    from telethon.errors import UserAlreadyParticipantError, InviteHashExpiredError

    invite_hash = _extract_hash(data.invite_link)
    chat_id: int | None = None
    chat_title: str = "Группа"
    joined_ids: list[int] = []
    errors: list[str] = []

    # Сначала узнаём chat_id и title через первый аккаунт (CheckChatInvite)
    first_account = await session.get(Account, data.account_ids[0])
    if first_account and first_account.is_active:
        try:
            client = await sm.get_client(first_account.id, first_account.session_string, first_account.proxy)
            info = await client(CheckChatInviteRequest(invite_hash))
            chat = getattr(info, 'chat', None)
            if chat is None and hasattr(info, 'chats') and info.chats:
                chat = info.chats[0]
            if chat:
                raw_id = chat.id
                chat_title = getattr(chat, 'title', 'Группа')
                if getattr(chat, 'megagroup', False) or getattr(chat, 'gigagroup', False):
                    chat_id = int(f"-100{raw_id}")
                else:
                    chat_id = -raw_id
        except Exception as e:
            logger.debug("CheckChatInvite error (will try to get id after join): %s", e)

    for account_id in data.account_ids:
        account = await session.get(Account, account_id)
        if not account or not account.is_active:
            errors.append(f"Аккаунт {account_id} не найден")
            continue

        try:
            client = await sm.get_client(account.id, account.session_string, account.proxy)
            try:
                result = await client(ImportChatInviteRequest(invite_hash))
                # Извлечь chat из любого типа ответа
                chats = getattr(result, 'chats', [])
                if chats and chat_id is None:
                    chat = chats[0]
                    raw_id = chat.id
                    chat_title = getattr(chat, 'title', 'Группа')
                    if getattr(chat, 'megagroup', False) or getattr(chat, 'gigagroup', False):
                        chat_id = int(f"-100{raw_id}")
                    else:
                        chat_id = -raw_id
                joined_ids.append(account_id)
                logger.info("Account %d joined group %s", account_id, chat_title)
            except UserAlreadyParticipantError:
                joined_ids.append(account_id)
                logger.info("Account %d already in group", account_id)
            except InviteHashExpiredError:
                raise HTTPException(status_code=400, detail="Invite-ссылка истекла или неверная")
        except HTTPException:
            raise
        except Exception as e:
            errors.append(f"Аккаунт {account_id}: {str(e)[:100]}")
            logger.warning("Account %d join error: %s", account_id, e)

    # Если chat_id всё ещё неизвестен — получить из диалогов первого успешного аккаунта
    if chat_id is None and joined_ids:
        try:
            account = await session.get(Account, joined_ids[0])
            client = await sm.get_client(account.id, account.session_string, account.proxy)
            async for dialog in client.iter_dialogs(limit=20):
                title = getattr(dialog.entity, 'title', '')
                if title == chat_title or (invite_hash and title):
                    chat_id = dialog.id
                    chat_title = title or chat_title
                    break
        except Exception as e:
            logger.warning("Could not resolve chat_id from dialogs: %s", e)

    if not joined_ids:
        raise HTTPException(status_code=400, detail=f"Ни один аккаунт не вступил. Ошибки: {errors}")

    if chat_id is None:
        raise HTTPException(status_code=500, detail="Не удалось определить ID группы")

    # Проверить нет ли уже активной сессии для этого чата
    existing = await session.execute(
        select(GroupChatSession).where(
            GroupChatSession.chat_id == chat_id,
            GroupChatSession.status == "running",
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Сессия для этой группы уже запущена")

    gs = GroupChatSession(
        chat_id=chat_id,
        chat_title=chat_title,
        invite_hash=invite_hash,
        account_ids=json.dumps(joined_ids),
        status="running",
        duration_days=data.duration_days,
        started_at=__import__('datetime').datetime.utcnow(),
    )
    session.add(gs)
    await session.commit()
    await session.refresh(gs)

    await group_chat_service.start_session(gs.id)

    if errors:
        logger.warning("Some accounts failed to join: %s", errors)

    return _out(gs)


@router.get("/sessions", response_model=list[GroupChatSessionOut])
async def list_sessions(session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(GroupChatSession).order_by(desc(GroupChatSession.created_at))
    )
    return [_out(s) for s in result.scalars().all()]


@router.delete("/sessions/{session_id}")
async def stop_session(session_id: int, session: AsyncSession = Depends(get_session)):
    gs = await session.get(GroupChatSession, session_id)
    if not gs:
        raise HTTPException(status_code=404)
    await group_chat_service.stop_session(session_id)
    gs.status = "stopped"
    await session.commit()
    return {"ok": True}


@router.get("/sessions/{session_id}/logs")
async def get_logs(session_id: int, limit: int = 100, session: AsyncSession = Depends(get_session)):
    limit = min(max(limit, 1), 500)
    result = await session.execute(
        select(GroupChatLog)
        .where(GroupChatLog.session_id == session_id)
        .order_by(desc(GroupChatLog.created_at))
        .limit(limit)
    )
    logs = result.scalars().all()
    return [
        {"id": l.id, "account_id": l.account_id, "action": l.action,
         "text": l.text, "created_at": l.created_at.isoformat()}
        for l in logs
    ]
