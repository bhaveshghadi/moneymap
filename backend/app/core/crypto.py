"""Encrypt secrets at rest (Gmail OAuth client secret and tokens).

The key is derived from the app's secret key (MONEYMAP_SECRET_KEY or
<data_dir>/secret_key), so a copy of the database alone doesn't reveal them.
If the secret key changes, stored secrets can't be read any more and the user
reconnects.
"""

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from ..config import get_settings


class DecryptError(Exception):
    pass


@lru_cache
def _fernet() -> Fernet:
    secret = get_settings().resolved_secret_key().encode()
    key = base64.urlsafe_b64encode(hashlib.sha256(b"moneymap-secrets:" + secret).digest())
    return Fernet(key)


def encrypt(text: str) -> str:
    return _fernet().encrypt(text.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        raise DecryptError("Stored secret can't be decrypted (the secret key changed?)") from None
