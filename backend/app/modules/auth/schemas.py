"""Auth request/response models (design B03 §3.8, api_spec.md §2).

Emails are trimmed and lower-cased here so every service compares one form
(the column is citext anyway). The format check is deliberately basic: the
real proof of an address is the verification email, and no extra dependency
(email-validator) is needed.
"""

import re
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_EMAIL_LEN = 254  # RFC 5321 path limit
MAX_PASSWORD_LEN = 1024  # bounds Argon2 work per request; min length is a service rule
MAX_TOKEN_LEN = 256  # raw tokens are 43 chars; anything far longer is garbage


def normalise_email(value: str) -> str:
    v = value.strip().lower()
    if len(v) > MAX_EMAIL_LEN or not EMAIL_RE.fullmatch(v):
        raise ValueError("invalid email address")
    return v


class _EmailField(BaseModel):
    email: str

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return normalise_email(v)


class LoginIn(_EmailField):
    # min_length=1 only: login must not reveal password rules (generic 401).
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LEN)


class EmailIn(_EmailField):
    pass


class TokenIn(BaseModel):
    token: str = Field(min_length=1, max_length=MAX_TOKEN_LEN)


class ResetPasswordIn(TokenIn):
    new_password: str = Field(min_length=1, max_length=MAX_PASSWORD_LEN)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=MAX_PASSWORD_LEN)
    new_password: str = Field(min_length=1, max_length=MAX_PASSWORD_LEN)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str | None
    is_verified: bool  # false -> UI shows "check your email" banner (B03 D1)
    is_platform_admin: bool


class MembershipOut(BaseModel):
    org_id: uuid.UUID
    slug: str
    name: str


class LoginOut(BaseModel):
    user: UserOut
    memberships: list[MembershipOut]


class SessionOut(BaseModel):
    """Returned by refresh: who the renewed session belongs to."""

    user: UserOut


class StatusOut(BaseModel):
    status: str
