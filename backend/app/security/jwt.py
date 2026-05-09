from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from jose import JWTError, jwt

from app.core.config import get_settings


@dataclass(frozen=True)
class IssuedToken:
    token: str
    jti: str
    expires_at: datetime


@dataclass(frozen=True)
class TokenData:
    subject: str
    token_type: str
    jti: str
    expires_at: datetime
    claims: dict[str, Any]


def _secret() -> str:
    return get_settings().jwt_secret.get_secret_value()


def _encode_token(
    subject: str,
    token_type: str,
    expires_delta: timedelta,
    **claims: Any,
) -> IssuedToken:
    settings = get_settings()
    now = datetime.now(UTC)
    expires_at = now + expires_delta
    jti = uuid.uuid4().hex
    payload = {
        "sub": subject,
        "typ": token_type,
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": expires_at,
        **claims,
    }
    token = jwt.encode(payload, _secret(), algorithm=settings.jwt_algorithm)
    return IssuedToken(token=token, jti=jti, expires_at=expires_at)


def create_access_token(subject: str, role: str) -> IssuedToken:
    settings = get_settings()
    return _encode_token(
        subject=subject,
        token_type="access",
        expires_delta=timedelta(minutes=settings.jwt_access_token_minutes),
        role=role,
    )


def create_refresh_token(subject: str) -> IssuedToken:
    settings = get_settings()
    return _encode_token(
        subject=subject,
        token_type="refresh",
        expires_delta=timedelta(days=settings.jwt_refresh_token_days),
    )


def issue_pdf_token(
    subject: str,
    document_id: str,
    knowledge_base_id: str | None = None,
) -> IssuedToken:
    settings = get_settings()
    return _encode_token(
        subject=subject,
        token_type="pdf_preview",
        expires_delta=timedelta(minutes=settings.pdf_token_minutes),
        doc=document_id,
        kb=knowledge_base_id,
        scope="pdf_preview",
    )


def decode_token(token: str, expected_type: str) -> TokenData:
    settings = get_settings()
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无效或已过期的认证凭据",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, _secret(), algorithms=[settings.jwt_algorithm])
        subject = payload.get("sub")
        token_type = payload.get("typ")
        jti = payload.get("jti")
        exp = payload.get("exp")
        if (
            not isinstance(subject, str)
            or not isinstance(token_type, str)
            or not isinstance(jti, str)
        ):
            raise credentials_error
        if token_type != expected_type:
            raise credentials_error
        expires_at = datetime.fromtimestamp(float(exp), tz=UTC)
        return TokenData(
            subject=subject,
            token_type=token_type,
            jti=jti,
            expires_at=expires_at,
            claims=payload,
        )
    except (JWTError, TypeError, ValueError) as exc:
        raise credentials_error from exc
