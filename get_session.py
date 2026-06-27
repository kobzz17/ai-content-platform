"""
Запусти этот скрипт чтобы получить session string для аккаунта.
Потом скопируй строку и добавь в импорт-файл для платформы.

Использование:
  python get_session.py +79001234567

Или без аргументов — спросит номер интерактивно.
"""
import asyncio
import sys
from telethon import TelegramClient
from telethon.sessions import StringSession

API_ID = 34542738
API_HASH = "5b44c8ddf1c3e89afb597ed6555227d1"


async def main():
    phone = sys.argv[1] if len(sys.argv) > 1 else input("Номер телефона (например +79001234567): ").strip()

    client = TelegramClient(StringSession(), API_ID, API_HASH)
    await client.connect()

    if not await client.is_user_authorized():
        await client.send_code_request(phone)
        code = input("Код из Telegram: ").strip()
        try:
            await client.sign_in(phone, code)
        except Exception:
            password = input("Пароль 2FA (если есть): ").strip()
            await client.sign_in(password=password)

    me = await client.get_me()
    session_string = client.session.save()

    print(f"\n✓ Аккаунт: {me.first_name} (@{me.username}), телефон: +{me.phone}")
    print("\n=== SESSION STRING (скопируй всю строку целиком) ===")
    print(session_string)
    print("====================================================\n")

    # Write to file
    label = input("Название аккаунта для платформы (Enter чтобы пропустить): ").strip()
    if label:
        import json
        filename = f"session_{me.id}.json"
        with open(filename, "w") as f:
            json.dump([{"session": session_string, "label": label}], f, ensure_ascii=False)
        print(f"✓ Сохранено в {filename} — можно загрузить через кнопку 'Импорт' в панели")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
