from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from src.database import get_session
from src.models import Account, AccountStatus
import src.session_manager as sm

router = APIRouter(prefix="/accounts", tags=["accounts"])


class AddPhoneRequest(BaseModel):
    phone: str
    label: str
    proxy: str | None = None


class ConfirmCodeRequest(BaseModel):
    phone: str
    code: str
    password: str | None = None  # 2FA
    label: str
    proxy: str | None = None


class AccountOut(BaseModel):
    id: int
    label: str
    phone: str
    username: str | None
    first_name: str | None
    avatar_color: str
    status: AccountStatus
    unread_count: int
    is_active: bool

    model_config = {"from_attributes": True}


@router.get("/", response_model=list[AccountOut])
async def list_accounts(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Account).where(Account.is_active == True))
    return result.scalars().all()


@router.post("/auth/start", status_code=202)
async def start_auth(data: AddPhoneRequest):
    """Send Telegram login code to the phone number."""
    try:
        await sm.start_auth(data.phone)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"message": "Code sent", "phone": data.phone}


@router.post("/auth/confirm", response_model=AccountOut, status_code=201)
async def confirm_auth(data: ConfirmCodeRequest, session: AsyncSession = Depends(get_session)):
    """Confirm login code, save account session."""
    try:
        session_string, me = await sm.complete_auth(data.phone, data.code, data.password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    account = Account(
        label=data.label or (me.first_name or data.phone),
        phone=data.phone,
        session_string=session_string,
        username=me.username,
        first_name=me.first_name,
        proxy=data.proxy,
    )
    session.add(account)
    await session.commit()
    await session.refresh(account)
    return account


@router.delete("/{account_id}", status_code=204)
async def remove_account(account_id: int, session: AsyncSession = Depends(get_session)):
    account = await session.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404)
    account.is_active = False
    await sm.disconnect_client(account_id)
    await session.commit()
