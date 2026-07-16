"""
Fernet-based encryption for sensitive DB fields (session strings).
Key is read from settings.session_encryption_key — must be 32 bytes (hex or raw).
"""
import base64
import hashlib
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator


def _get_fernet() -> Fernet:
    from src.config import settings
    key = settings.session_encryption_key
    # Derive a 32-byte key from whatever the user put in .env
    raw = hashlib.sha256(key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(raw))


def encrypt(value: str) -> str:
    return _get_fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    return _get_fernet().decrypt(value.encode()).decode()


class EncryptedText(TypeDecorator):
    """SQLAlchemy column type that transparently encrypts/decrypts values."""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return encrypt(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        try:
            return decrypt(value)
        except (InvalidToken, Exception):
            # Plaintext value not yet migrated — return as-is
            return value
