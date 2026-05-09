from __future__ import annotations

import base64
import hashlib
import hmac
import os

SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
DKLEN = 64


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=DKLEN,
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}" f"${_b64encode(salt)}${_b64encode(derived)}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        scheme, n_raw, r_raw, p_raw, salt_raw, digest_raw = password_hash.split("$", 5)
        if scheme != "scrypt":
            return False
        salt = _b64decode(salt_raw)
        expected = _b64decode(digest_raw)
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(n_raw),
            r=int(r_raw),
            p=int(p_raw),
            dklen=len(expected),
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False
