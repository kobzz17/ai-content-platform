from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
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


class BatchImportResult(BaseModel):
    ok: list[AccountOut] = []
    failed: list[dict] = []


@router.post("/import-batch", response_model=BatchImportResult, status_code=200)
async def import_batch(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
):
    """
    Bulk import accounts from a JSON or plain-text file.

    JSON format:
      [{"session": "...", "label": "Account 1"}, ...]

    Plain text format (one session string per line, optional label after tab):
      1BQANOTEuMDAAA...   Account 1
      1BQANOTEuMDAAB...   Account 2
    """
    import json
    content = (await file.read()).decode("utf-8").strip()

    # Parse input
    entries: list[dict] = []
    if content.startswith("[") or content.startswith("{"):
        raw = json.loads(content)
        if isinstance(raw, list):
            entries = raw
        else:
            entries = [raw]
    else:
        for i, line in enumerate(content.splitlines()):
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t", 1)
            entries.append({
                "session": parts[0].strip(),
                "label": parts[1].strip() if len(parts) > 1 else f"Аккаунт {i+1}",
            })

    ok: list[Account] = []
    failed: list[dict] = []

    for entry in entries:
        session_str = entry.get("session", "").strip()
        label = entry.get("label", "Импортированный аккаунт")
        if not session_str:
            failed.append({"label": label, "error": "Пустая session string"})
            continue

        # Check duplicate
        existing = await session.execute(
            select(Account).where(Account.session_string == session_str)
        )
        if existing.scalar_one_or_none():
            failed.append({"label": label, "error": "Аккаунт уже существует"})
            continue

        try:
            # Test the session string by connecting
            from src.config import settings
            from telethon import TelegramClient
            from telethon.sessions import StringSession
            client = TelegramClient(
                StringSession(session_str),
                settings.telegram_api_id,
                settings.telegram_api_hash,
            )
            await client.connect()
            if not await client.is_user_authorized():
                await client.disconnect()
                failed.append({"label": label, "error": "Сессия истекла или не авторизована"})
                continue
            me = await client.get_me()
            await client.disconnect()

            # Save the phone properly
            phone = getattr(me, "phone", None) or f"unknown_{me.id}"
            if not phone.startswith("+"):
                phone = f"+{phone}"

            # Check phone duplicate
            phone_exists = await session.execute(
                select(Account).where(Account.phone == phone)
            )
            if phone_exists.scalar_one_or_none():
                failed.append({"label": label, "error": f"Номер {phone} уже зарегистрирован"})
                continue

            account = Account(
                label=label,
                phone=phone,
                session_string=session_str,
                username=me.username,
                first_name=me.first_name,
            )
            session.add(account)
            await session.flush()
            await session.refresh(account)
            ok.append(account)
        except Exception as e:
            failed.append({"label": label, "error": str(e)[:120]})

    await session.commit()
    return BatchImportResult(ok=[AccountOut.model_validate(a) for a in ok], failed=failed)


@router.post("/import-tdata", response_model=BatchImportResult, status_code=200)
async def import_tdata(
    file: UploadFile = File(...),
    passcode: str = "",
    session: AsyncSession = Depends(get_session),
):
    """
    Import accounts from a ZIP file containing one or more tdata folders.

    The ZIP may contain:
      - A single tdata/ at the root
      - Multiple directories each with a tdata/ subfolder
      - Multiple tdata folders directly (any dir containing key_datas/key_data0/key_data1)
    """
    import zipfile
    import tempfile
    import os
    from src.services.tdata_reader import read_tdata
    from src.config import settings
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    raw = await file.read()

    ok: list[Account] = []
    failed: list[dict] = []

    with tempfile.TemporaryDirectory(prefix="tdata_import_") as tmp:
        zip_path = os.path.join(tmp, "upload.zip")
        with open(zip_path, "wb") as f:
            f.write(raw)

        try:
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(tmp)
        except zipfile.BadZipFile:
            raise HTTPException(status_code=400, detail="Не ZIP-архив")

        # Find all tdata directories inside the extracted tree
        tdata_dirs: list[str] = []
        for dirpath, dirnames, filenames in os.walk(tmp):
            # Skip the root tmp dir itself
            if dirpath == tmp:
                continue
            # A tdata folder has key_datas, key_data0, or key_data1
            for fname in filenames:
                if fname.startswith("key_data"):
                    tdata_dirs.append(dirpath)
                    break

        if not tdata_dirs:
            raise HTTPException(
                status_code=400,
                detail="В архиве не найдено папок tdata (нет файлов key_data*)",
            )

        for tdata_path in tdata_dirs:
            label = f"tdata/{os.path.basename(os.path.dirname(tdata_path)) or os.path.basename(tdata_path)}"
            try:
                sessions_found = read_tdata(tdata_path, passcode=passcode)
            except Exception as e:
                failed.append({"label": label, "error": f"Чтение tdata: {e}"})
                continue

            if not sessions_found:
                failed.append({"label": label, "error": "Не найдено аккаунтов в tdata"})
                continue

            for sess in sessions_found:
                session_str = sess["session_string"]
                acc_label = label

                # Check for duplicate session
                existing = await session.execute(
                    select(Account).where(Account.session_string == session_str)
                )
                if existing.scalar_one_or_none():
                    failed.append({"label": acc_label, "error": "Аккаунт уже импортирован"})
                    continue

                try:
                    client = TelegramClient(
                        StringSession(session_str),
                        settings.telegram_api_id,
                        settings.telegram_api_hash,
                    )
                    await client.connect()
                    if not await client.is_user_authorized():
                        await client.disconnect()
                        failed.append({"label": acc_label, "error": "Сессия истекла"})
                        continue
                    me = await client.get_me()
                    await client.disconnect()

                    phone = getattr(me, "phone", None) or f"id_{me.id}"
                    if not phone.startswith("+"):
                        phone = f"+{phone}"
                    acc_label = me.first_name or phone

                    # Check phone duplicate
                    phone_exists = await session.execute(
                        select(Account).where(Account.phone == phone)
                    )
                    if phone_exists.scalar_one_or_none():
                        failed.append({"label": acc_label, "error": f"Номер {phone} уже зарегистрирован"})
                        continue

                    account = Account(
                        label=acc_label,
                        phone=phone,
                        session_string=session_str,
                        username=getattr(me, "username", None),
                        first_name=getattr(me, "first_name", None),
                    )
                    session.add(account)
                    await session.flush()
                    await session.refresh(account)
                    ok.append(account)
                except Exception as e:
                    failed.append({"label": acc_label, "error": str(e)[:120]})

    await session.commit()
    return BatchImportResult(ok=[AccountOut.model_validate(a) for a in ok], failed=failed)


@router.delete("/{account_id}", status_code=204)
async def remove_account(account_id: int, session: AsyncSession = Depends(get_session)):
    account = await session.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404)
    account.is_active = False
    await sm.disconnect_client(account_id)
    await session.commit()
