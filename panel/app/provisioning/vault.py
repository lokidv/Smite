"""Symmetric encryption for stored SSH / proxy passwords.

The panel persists WARP/proxy server SSH credentials so it can re-apply a proxy
change over SSH later. Passwords are Fernet-encrypted with a key derived from
the panel ``secret_key`` (which is already a strong random value, see
``config._ensure_secret_key``). They are never written to the DB in plaintext.
"""
from __future__ import annotations

import base64
import hashlib
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


def _fernet() -> Fernet:
    # Derive a valid 32-byte urlsafe-base64 Fernet key from the panel secret.
    digest = hashlib.sha256((settings.secret_key or "").encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt(plaintext: Optional[str]) -> Optional[str]:
    """Encrypt a secret; returns a Fernet token string, or None for empty input."""
    if plaintext is None or plaintext == "":
        return None
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(token: Optional[str]) -> str:
    """Decrypt a Fernet token; returns "" for None/empty or an unreadable token."""
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return ""
