from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from src.database import get_session
from src.models import Account
import src.session_manager as sm

router = APIRouter(prefix="/accounts/{account_id}", tags=["messages"])


class DialogOut(BaseModel):
    id: int
    name: str
    unread_count: int
    last_message: str | None
    last_message_date: str | None
    is_group: bool


class MessageOut(BaseModel):
    id: int
    sender: str
    text: str
    date: str
    is_outgoing: bool


class SendRequest(BaseModel):
    chat_id: int
    text: str


DEMO_DIALOGS = [
    DialogOut(id=-1001234567890, name="Команда разработки 🔧", unread_count=3,
              last_message="Согласен, особенно нравится интеграция с PR",
              last_message_date="2026-06-26T14:20:00", is_group=True),
    DialogOut(id=-1009876543210, name="Маркетинг и продажи 📈", unread_count=0,
              last_message="Метрики за прошлую неделю неплохие",
              last_message_date="2026-06-26T13:45:00", is_group=True),
    DialogOut(id=100000001, name="Иван Петров", unread_count=1,
              last_message="Привет, когда встреча?",
              last_message_date="2026-06-26T12:30:00", is_group=False),
]

DEMO_MESSAGES: dict[int, list[MessageOut]] = {
    -1001234567890: [
        MessageOut(id=1, sender="Иван", text="Кстати, кто-нибудь пробовал новый подход к деплою через GitHub Actions?", date="2026-06-26T13:00:00", is_outgoing=False),
        MessageOut(id=2, sender="You", text="Да, мы тоже переходим. Пока настраиваем, но уже видно что удобнее.", date="2026-06-26T13:05:00", is_outgoing=True),
        MessageOut(id=3, sender="Мария", text="Согласна! Особенно удобно что статус видно прямо в PR.", date="2026-06-26T13:08:00", is_outgoing=False),
        MessageOut(id=4, sender="You", text="Вопрос к команде: как вы организуете code review? Есть чеклист?", date="2026-06-26T13:20:00", is_outgoing=True),
        MessageOut(id=5, sender="Иван", text="У нас есть базовый, но соблюдается процентов на 70. Думаем автоматизировать.", date="2026-06-26T13:25:00", is_outgoing=False),
        MessageOut(id=6, sender="You", text="Линтеры хорошо помогают. ESLint + тесты закрывают основное.", date="2026-06-26T14:20:00", is_outgoing=True),
    ],
    -1009876543210: [
        MessageOut(id=1, sender="Ольга", text="Конкурент запустил рассылку через Telegram — +15% к конверсии за неделю.", date="2026-06-26T12:00:00", is_outgoing=False),
        MessageOut(id=2, sender="You", text="Интересный кейс. Стоит нам попробовать?", date="2026-06-26T12:05:00", is_outgoing=True),
        MessageOut(id=3, sender="Ольга", text="Думаю да. Надо обсудить формат.", date="2026-06-26T12:10:00", is_outgoing=False),
        MessageOut(id=4, sender="You", text="Метрики за прошлую неделю неплохие, органика выросла на 12%.", date="2026-06-26T13:45:00", is_outgoing=True),
    ],
    100000001: [
        MessageOut(id=1, sender="Иван Петров", text="Привет! Когда у нас встреча по проекту?", date="2026-06-26T12:30:00", is_outgoing=False),
    ],
}


async def _get_account_client(account_id: int, session: AsyncSession):
    account = await session.get(Account, account_id)
    if not account or not account.is_active:
        raise HTTPException(status_code=404, detail="Account not found")
    if account.session_string == "DEMO":
        return None  # demo mode
    try:
        client = await sm.get_client(account_id, account.session_string, account.proxy)
    except RuntimeError as e:
        raise HTTPException(status_code=401, detail=str(e))
    return client


@router.get("/dialogs", response_model=list[DialogOut])
async def get_dialogs(
    account_id: int,
    limit: int = 30,
    session: AsyncSession = Depends(get_session),
):
    """List recent dialogs (chats, groups, channels) for an account."""
    client = await _get_account_client(account_id, session)
    if client is None:
        return DEMO_DIALOGS
    dialogs = []
    async for dialog in client.iter_dialogs(limit=limit):
        last_msg = dialog.message
        dialogs.append(DialogOut(
            id=dialog.id,
            name=dialog.name or "—",
            unread_count=dialog.unread_count,
            last_message=last_msg.text[:80] if last_msg and last_msg.text else None,
            last_message_date=last_msg.date.isoformat() if last_msg else None,
            is_group=dialog.is_group or dialog.is_channel,
        ))
    return dialogs


@router.get("/dialogs/{chat_id}/messages", response_model=list[MessageOut])
async def get_messages(
    account_id: int,
    chat_id: int,
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
):
    """Fetch recent messages from a chat."""
    client = await _get_account_client(account_id, session)
    if client is None:
        return DEMO_MESSAGES.get(chat_id, [])
    me = await client.get_me()
    messages = []
    async for msg in client.iter_messages(chat_id, limit=limit):
        if not msg.text:
            continue
        sender_name = "You" if msg.out else (
            getattr(msg.sender, "first_name", None) or
            getattr(msg.sender, "title", None) or
            "Unknown"
        )
        messages.append(MessageOut(
            id=msg.id,
            sender=sender_name,
            text=msg.text,
            date=msg.date.isoformat(),
            is_outgoing=msg.out,
        ))
    return list(reversed(messages))  # oldest first


@router.post("/dialogs/{chat_id}/send", status_code=201)
async def send_message(
    account_id: int,
    chat_id: int,
    data: SendRequest,
    session: AsyncSession = Depends(get_session),
):
    """Send a message from this account to a chat."""
    client = await _get_account_client(account_id, session)
    sent = await client.send_message(chat_id, data.text)
    return {"message_id": sent.id, "date": sent.date.isoformat()}
