"""Cryptographic helpers for opaque sessions and encrypted provider tokens."""

from __future__ import annotations

import base64
import hashlib
import secrets
from collections.abc import Sequence

from cryptography.fernet import Fernet, InvalidToken


def random_url_token(size: int = 32) -> str:
    return secrets.token_urlsafe(size)


def digest_token(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class TokenCipher:
    """Fernet encrypt/decrypt with ordered keys for controlled key rotation."""

    def __init__(self, keys: Sequence[str]):
        if not keys:
            raise ValueError("at least one token encryption key is required")
        self._encryptor = Fernet(keys[0].encode("ascii"))
        self._decryptors = tuple(Fernet(key.encode("ascii")) for key in keys)

    @staticmethod
    def generate_key() -> str:
        return Fernet.generate_key().decode("ascii")

    def encrypt(self, value: str) -> str:
        return self._encryptor.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, value: str) -> str:
        for cipher in self._decryptors:
            try:
                return cipher.decrypt(value.encode("ascii")).decode("utf-8")
            except InvalidToken:
                continue
        raise InvalidToken("encrypted authentication value cannot be decrypted")


def random_cookie_value() -> str:
    return (
        base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")
    )
