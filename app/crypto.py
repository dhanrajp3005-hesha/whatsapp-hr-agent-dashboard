from functools import lru_cache

from cryptography.fernet import Fernet

from app.config import APP_ENCRYPTION_KEY, require_encryption_key


@lru_cache
def get_fernet() -> Fernet:
    """
    Public accessor - used directly (not just via encrypt_secret/
    decrypt_secret below) by app/auth.py, which needs Fernet's ttl=
    support on decrypt() for session cookie expiry that encrypt_secret/
    decrypt_secret don't need for SMTP passwords.
    """

    require_encryption_key()
    return Fernet(APP_ENCRYPTION_KEY.encode())


def encrypt_secret(plaintext: str) -> str:
    return get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    return get_fernet().decrypt(ciphertext.encode()).decode()
