from functools import lru_cache

from cryptography.fernet import Fernet

from app.config import APP_ENCRYPTION_KEY, require_encryption_key


@lru_cache
def _fernet() -> Fernet:
    require_encryption_key()
    return Fernet(APP_ENCRYPTION_KEY.encode())


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode()).decode()
