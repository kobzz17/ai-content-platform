"""
Run this script directly in the terminal to authenticate a Telegram account.
It will ask for phone number and code interactively, then print the session string
that you can paste into the database or use with the main app.

Usage:
    cd /Users/kobz/ai-content-platform/backend
    .venv/bin/python auth_helper.py
"""
import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession
from src.config import settings


async def main():
    print("\n=== Telegram Auth Helper ===\n")
    client = TelegramClient(StringSession(), settings.telegram_api_id, settings.telegram_api_hash)

    # client.start() handles the full flow: phone → code → 2FA
    await client.start()

    me = await client.get_me()
    session_string = client.session.save()

    print(f"\n✅ Авторизован как: {me.first_name} (@{me.username})")
    print(f"📱 Телефон: {me.phone}")
    print(f"\n🔑 Session string (сохрани его!):\n{session_string}\n")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
