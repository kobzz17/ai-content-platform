"""
One-time migration: encrypt all plaintext session_strings in the DB.
Run ONCE after deploying crypto.py + updated models.py.

Usage:
    cd backend && .venv/bin/python migrate_encrypt_sessions.py
"""
import asyncio
from sqlalchemy import text
from src.database import async_session_maker, init_db
from src.crypto import encrypt, decrypt
from cryptography.fernet import InvalidToken


async def main():
    await init_db()

    async with async_session_maker() as db:
        # Read raw values bypassing the TypeDecorator
        rows = (await db.execute(text("SELECT id, session_string FROM accounts WHERE is_active = 1"))).fetchall()

    print(f"Found {len(rows)} active accounts")
    migrated = 0
    skipped = 0

    async with async_session_maker() as db:
        for row in rows:
            acc_id, raw = row
            # Check if already encrypted (Fernet tokens start with "gAAAAA")
            if raw and raw.startswith("gAAAAA"):
                skipped += 1
                continue
            if not raw:
                skipped += 1
                continue
            encrypted = encrypt(raw)
            # Verify round-trip before writing
            assert decrypt(encrypted) == raw, f"Round-trip failed for account {acc_id}"
            await db.execute(
                text("UPDATE accounts SET session_string = :enc WHERE id = :id"),
                {"enc": encrypted, "id": acc_id},
            )
            migrated += 1

        await db.commit()

    print(f"Done: {migrated} encrypted, {skipped} already encrypted or skipped")


if __name__ == "__main__":
    asyncio.run(main())
