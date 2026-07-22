import hashlib


def calculate_hash(message: str) -> str:
    return hashlib.sha256(message.encode("utf-8")).hexdigest()
