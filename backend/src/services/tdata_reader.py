"""
Custom Telegram Desktop tdata reader — Python 3.14 compatible.
Reads tdata folders and extracts Telethon StringSession strings.

Implements the TDesktop storage format:
  - TDF$ file format with MD5 checksum
  - AES-IGE decryption via tgcrypto
  - MTProto v1 key expansion (prepareAES_oldmtp)
  - QDataStream big-endian integer encoding
"""

import hashlib
import struct
import socket
import base64
from pathlib import Path

import tgcrypto

TDF_MAGIC = b"TDF$"

# Production DC IPs (IPv4)
DC_IPS = {
    1: ("149.154.175.53", 443),
    2: ("149.154.167.51", 443),
    3: ("149.154.175.100", 443),
    4: ("149.154.167.91", 443),
    5: ("91.108.56.130", 443),
}

# dbi.MtpAuthorization block ID
DBI_MTP_AUTHORIZATION = 75

# Wide user IDs tag: ~0 as uint64 (stored as int64=-1 << int32 pair)
_WIDE_IDS_TAG = (1 << 64) - 1


# ── File reading ──────────────────────────────────────────────────────────────

def _read_tdf_file(base_path: Path, name: str) -> tuple[bytes, int] | None:
    """Read a TDesktop file (tries suffixes s/1/0), verify MD5, return (data, version)."""
    for suffix in ["s", "1", "0"]:
        p = base_path / (name + suffix)
        if not p.exists():
            continue
        try:
            raw = p.read_bytes()
        except OSError:
            continue

        if len(raw) < 24 or raw[:4] != TDF_MAGIC:
            continue

        version = int.from_bytes(raw[4:8], "little")
        payload = raw[8:]
        data_size = len(payload) - 16
        if data_size < 0:
            continue

        data = payload[:data_size]
        md5_stored = payload[data_size:]

        check = (
            data
            + data_size.to_bytes(4, "little")
            + version.to_bytes(4, "little")
            + TDF_MAGIC
        )
        if hashlib.md5(check).digest() == md5_stored:
            return data, version

    return None


# ── QDataStream primitives (big-endian, Qt 5.1) ───────────────────────────────

def _qba(data: bytes, pos: int) -> tuple[bytes | None, int]:
    """Read QByteArray from pos. Returns (bytes_or_None, new_pos)."""
    if pos + 4 > len(data):
        raise ValueError(f"QByteArray size read overflow at pos {pos}")
    (size,) = struct.unpack_from(">I", data, pos)
    pos += 4
    if size == 0xFFFFFFFF:
        return None, pos
    if pos + size > len(data):
        raise ValueError(f"QByteArray data overflow: need {size}, have {len(data)-pos}")
    return data[pos : pos + size], pos + size


def _i32(data: bytes, pos: int) -> tuple[int, int]:
    (v,) = struct.unpack_from(">i", data, pos)
    return v, pos + 4


def _u32(data: bytes, pos: int) -> tuple[int, int]:
    (v,) = struct.unpack_from(">I", data, pos)
    return v, pos + 4


def _u64(data: bytes, pos: int) -> tuple[int, int]:
    (v,) = struct.unpack_from(">Q", data, pos)
    return v, pos + 8


# ── Cryptography ──────────────────────────────────────────────────────────────

def _create_local_key(salt: bytes, passcode: bytes = b"") -> bytes:
    """
    Modern TDesktop key derivation (CreateLocalKey).
    key = PBKDF2-SHA512(sha512(salt+passcode+salt), salt, iterations=1, 256)
    """
    h = hashlib.sha512(salt + passcode + salt).digest()
    iterations = 1 if not passcode else 100000
    return hashlib.pbkdf2_hmac("sha512", h, salt, iterations, dklen=256)


def _prepare_aes_decrypt(auth_key: bytes, msg_key: bytes) -> tuple[bytes, bytes]:
    """MTProto v1 AES key+IV derivation for decryption (x=8)."""
    x = 8
    sha1 = lambda *parts: hashlib.sha1(b"".join(parts)).digest()
    a = sha1(msg_key[:16], auth_key[x : x + 32])
    b = sha1(auth_key[x + 32 : x + 48], msg_key[:16], auth_key[x + 48 : x + 64])
    c = sha1(auth_key[x + 64 : x + 96], msg_key[:16])
    d = sha1(msg_key[:16], auth_key[x + 96 : x + 128])
    aes_key = a[:8] + b[8:20] + c[4:16]
    aes_iv = a[8:20] + b[:8] + c[16:20] + d[:8]
    return aes_key, aes_iv


def _decrypt_local(encrypted: bytes, auth_key: bytes) -> bytes:
    """
    Decrypt AES-IGE blob:
      [16 bytes msgKey=sha1(plain)[:16]] + [N bytes AES-IGE encrypted]
    Returns plaintext (after stripping the 4-byte LE length prefix).
    """
    if len(encrypted) <= 16 or len(encrypted) % 16 != 0:
        raise ValueError(f"Bad encrypted size: {len(encrypted)}")

    msg_key = encrypted[:16]
    enc_data = encrypted[16:]
    aes_key, aes_iv = _prepare_aes_decrypt(auth_key, msg_key)
    decrypted = tgcrypto.ige256_decrypt(enc_data, aes_key, aes_iv)

    if hashlib.sha1(decrypted).digest()[:16] != msg_key:
        raise ValueError("SHA1 mismatch — wrong key or corrupt data")

    data_len = int.from_bytes(decrypted[:4], "little")
    if data_len > len(decrypted) or data_len < 4:
        raise ValueError(f"Bad decrypted data_len: {data_len}")

    return decrypted[4:data_len]


# ── Filename helpers ──────────────────────────────────────────────────────────

def _compute_data_name_key(data_name: str) -> int:
    """MD5(data_name) as LE 128-bit int (ToFilePart only uses low 64 bits)."""
    return int.from_bytes(hashlib.md5(data_name.encode()).digest(), "little")


def _to_file_part(val: int) -> str:
    """Convert key to 16-char hex filename (TDesktop convention)."""
    result = []
    for _ in range(16):
        v = val & 0xF
        result.append(chr(ord("0") + v) if v < 10 else chr(ord("A") + v - 10))
        val >>= 4
    return "".join(result)


def _compose_data_string(key_file: str, index: int) -> str:
    """'data' → 'data', index=1 → 'data#2', etc."""
    base = key_file.replace("#", "")
    return base if index == 0 else f"{base}#{index + 1}"


# ── Telethon session ──────────────────────────────────────────────────────────

def _make_telethon_session(dc_id: int, auth_key: bytes) -> str:
    """Build Telethon StringSession v1 from DC id and 256-byte auth key."""
    ip, port = DC_IPS.get(dc_id, ("149.154.167.51", 443))
    ip_bytes = socket.inet_aton(ip)
    data = struct.pack(f">B{len(ip_bytes)}sH256s", dc_id, ip_bytes, port, auth_key)
    return "1" + base64.urlsafe_b64encode(data).decode("ascii")


# ── Public API ────────────────────────────────────────────────────────────────

def read_tdata(tdata_path: str, passcode: str = "", key_file: str = "data") -> list[dict]:
    """
    Read a Telegram Desktop tdata folder.

    Args:
        tdata_path: Path to the tdata directory.
        passcode:   Passcode / local password (empty string if none).
        key_file:   Key file name prefix (default "data").

    Returns:
        List of dicts, one per account:
          {
            "dc_id": int,
            "user_id": int,
            "session_string": str,   # Telethon StringSession
          }

    Raises:
        FileNotFoundError: key_data file not found.
        ValueError: Decryption failed (wrong passcode, corrupt data, etc.).
    """
    base = Path(tdata_path)
    passcode_bytes = passcode.encode("utf-8") if passcode else b""

    # ── 1. Read key_data ──────────────────────────────────────────────────────
    result = _read_tdf_file(base, f"key_{key_file}")
    if result is None:
        raise FileNotFoundError(f"key_{key_file}[s/1/0] not found in {tdata_path}")

    key_data, _ = result
    pos = 0

    salt, pos = _qba(key_data, pos)
    if salt is None or len(salt) != 32:
        raise ValueError(f"Bad salt size: {len(salt) if salt else 'null'}")

    key_encrypted, pos = _qba(key_data, pos)
    if not key_encrypted:
        raise ValueError("Missing encrypted key blob")

    info_encrypted, pos = _qba(key_data, pos)
    if not info_encrypted:
        raise ValueError("Missing encrypted account info blob")

    # ── 2. Derive passcode key → decrypt local key ────────────────────────────
    passcode_key = _create_local_key(salt, passcode_bytes)

    local_key_raw = _decrypt_local(key_encrypted, passcode_key)
    if len(local_key_raw) < 256:
        raise ValueError(f"LocalKey too short: {len(local_key_raw)}")
    local_key = local_key_raw[:256]

    # ── 3. Decrypt account index list ─────────────────────────────────────────
    info_data = _decrypt_local(info_encrypted, local_key)
    i_pos = 0
    account_count, i_pos = _i32(info_data, i_pos)
    if not (0 < account_count <= 100):
        raise ValueError(f"Invalid account count: {account_count}")

    account_indices = []
    for _ in range(account_count):
        idx, i_pos = _i32(info_data, i_pos)
        account_indices.append(idx)

    # ── 4. Read MTP auth data for each account ────────────────────────────────
    sessions: list[dict] = []

    for idx in account_indices:
        data_name = _compose_data_string(key_file, idx)
        data_name_key = _compute_data_name_key(data_name)
        file_part = _to_file_part(data_name_key)

        mtp_result = _read_tdf_file(base, file_part)
        if mtp_result is None:
            continue

        mtp_data, _ = mtp_result
        m_pos = 0

        # File contains one QByteArray = encrypted MTP auth blob
        enc_blob, _ = _qba(mtp_data, m_pos)
        if not enc_blob:
            continue

        try:
            decrypted = _decrypt_local(enc_blob, local_key)
        except ValueError:
            continue

        # Decrypted: int32 blockId + QByteArray serialized
        d_pos = 0
        block_id, d_pos = _i32(decrypted, d_pos)
        if block_id != DBI_MTP_AUTHORIZATION:
            continue

        serialized, _ = _qba(decrypted, d_pos)
        if not serialized:
            continue

        # Parse serialized MTP authorization
        a_pos = 0
        user_id_raw, a_pos = _i32(serialized, a_pos)
        dc_id_raw, a_pos = _i32(serialized, a_pos)

        # Wide IDs tag: first two int32s pack to 0xFFFFFFFFFFFFFFFF
        combined = ((user_id_raw & 0xFFFFFFFF) << 32) | (dc_id_raw & 0xFFFFFFFF)
        if combined == _WIDE_IDS_TAG:
            user_id, a_pos = _u64(serialized, a_pos)
            main_dc_id, a_pos = _i32(serialized, a_pos)
        else:
            user_id = user_id_raw
            main_dc_id = dc_id_raw

        # Read auth keys map { dc_id → 256-byte key }
        key_count, a_pos = _i32(serialized, a_pos)
        if not (0 < key_count <= 50):
            continue

        auth_keys: dict[int, bytes] = {}
        for _ in range(key_count):
            dc, a_pos = _i32(serialized, a_pos)
            key_bytes = serialized[a_pos : a_pos + 256]
            a_pos += 256
            auth_keys[dc] = key_bytes

        if main_dc_id not in auth_keys:
            continue

        sessions.append(
            {
                "dc_id": main_dc_id,
                "user_id": user_id,
                "session_string": _make_telethon_session(main_dc_id, auth_keys[main_dc_id]),
            }
        )

    return sessions
