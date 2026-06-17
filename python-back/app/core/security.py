import base64
import hashlib

from cryptography.fernet import Fernet


def build_secret_fingerprint(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()[:16]


class SecretCipher:
    def __init__(self, master_key: str):
        if not master_key:
            raise ValueError("CONFIG_MASTER_KEY is required for secret encryption")
        self._fernet = Fernet(self._normalize_key(master_key))

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("utf-8")

    def decrypt(self, value: str) -> str:
        return self._fernet.decrypt(value.encode("utf-8")).decode("utf-8")

    @staticmethod
    def _normalize_key(master_key: str) -> bytes:
        raw = master_key.strip()
        if len(raw) == 44:
            return raw.encode("utf-8")
        digest = hashlib.sha256(raw.encode("utf-8")).digest()
        return base64.urlsafe_b64encode(digest)
