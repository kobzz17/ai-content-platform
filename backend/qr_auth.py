"""
QR-code based Telegram authentication — no SMS/app code needed.

Usage:
    cd /Users/kobz/ai-content-platform/backend
    .venv/bin/python qr_auth.py

Then scan the QR code with Telegram on your phone:
  Telegram → Settings → Devices → Link Desktop Device → scan QR
"""
import asyncio
import qrcode
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError
from src.config import settings


async def main():
    label = input("Введи название аккаунта (например 'Алексей'): ").strip() or "Аккаунт"

    client = TelegramClient(StringSession(), settings.telegram_api_id, settings.telegram_api_hash)
    await client.connect()

    print("\n📱 Открой Telegram на телефоне:")
    print("   Настройки → Устройства → Подключить устройство → сканируй QR\n")

    qr_login = await client.qr_login()

    # Print QR to terminal
    qr = qrcode.QRCode(border=1)
    qr.add_data(qr_login.url)
    qr.print_ascii(invert=True)

    print(f"\nURL: {qr_login.url}\n")
    print("⏳ Жду сканирования (60 сек)...")

    try:
        await qr_login.wait(60)
    except SessionPasswordNeededError:
        pwd = input("🔐 Введи пароль 2FA: ")
        await client.sign_in(password=pwd)
    except asyncio.TimeoutError:
        print("❌ Время вышло. Запусти скрипт снова.")
        await client.disconnect()
        return

    me = await client.get_me()
    session_string = client.session.save()

    print(f"\n✅ Авторизован: {me.first_name} (@{me.username}) · {me.phone}")
    print(f"\n🔑 Session string:\n{session_string}\n")

    # Auto-save to DB
    save = input("Сохранить этот аккаунт в панель? (y/n): ").strip().lower()
    if save == "y":
        from src.database import init_db, async_session_maker
        from src.models import Account, AccountStatus
        import random

        colors = ["#5b8af7", "#e85d75", "#3ec97e", "#f59e0b", "#a78bfa"]
        await init_db()
        async with async_session_maker() as db:
            existing = await db.execute(
                __import__("sqlalchemy").select(Account).where(Account.phone == str(me.phone))
            )
            if existing.scalar_one_or_none():
                print("⚠️  Аккаунт с этим номером уже есть в базе.")
            else:
                acc = Account(
                    label=label,
                    phone=str(me.phone),
                    first_name=me.first_name,
                    username=me.username,
                    session_string=session_string,
                    avatar_color=random.choice(colors),
                    status=AccountStatus.active,
                )
                db.add(acc)
                await db.commit()
                print(f"✅ Аккаунт '{label}' сохранён в панели!")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
