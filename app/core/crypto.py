import base64
import hashlib
from functools import lru_cache
from cryptography.fernet import Fernet, InvalidToken
from app.config import settings


@lru_cache(maxsize=1)
def _get_fernet() -> Fernet:
    key = settings.encryption_key
    if not key:
        # Dev fallback: derive from JWT secret so no extra config is needed locally.
        # Production is blocked at startup if ENCRYPTION_KEY is missing (see config.py).
        raw = hashlib.sha256(settings.jwt_secret_key.encode()).digest()
        key = base64.urlsafe_b64encode(raw).decode()
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_token(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: str) -> str | None:
    try:
        return _get_fernet().decrypt(ciphertext.encode()).decode()
    except (InvalidToken, ValueError):
        return None
