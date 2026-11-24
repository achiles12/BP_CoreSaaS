"""Users / me / invitations request-response models (design B04 §3.4)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.modules.auth.schemas import (
    MAX_PASSWORD_LEN,
    MAX_TOKEN_LEN,
    UserOut,
    normalise_email,
)

MAX_NAME_LEN = 200


def _clean_name(v: str) -> str:
    v = " ".join(v.split())  # trim + collapse inner whitespace
    if not v:
        raise ValueError("must not be empty")
    return v


class OrgRef(BaseModel):
    id: uuid.UUID
    slug: str
    name: str


class MeOut(BaseModel):
    """GET /me (api_spec.md §3). `landing_path` drives the post-login redirect."""

    user: UserOut
    org: OrgRef | None
    roles: list[str]
    permissions: list[str]
    landing_path: str | None  # null: no organization (B04 D15)
    is_platform_admin: bool
    is_verified: bool


class NameIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=MAX_NAME_LEN)

    @field_validator("full_name")
    @classmethod
    def _name(cls, v: str) -> str:
        return _clean_name(v)


class MemberOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str | None
    status: str  # membership status: active | inactive
    is_verified: bool
    roles: list[str]
    joined_at: datetime


class InviteIn(BaseModel):
    email: str
    role_key: str = Field(min_length=1, max_length=50)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return normalise_email(v)


class InvitationOut(BaseModel):
    id: uuid.UUID
    email: str
    role_key: str
    invited_by: str | None  # inviter email; null for CLI invitations
    created_at: datetime
    expires_at: datetime
    expired: bool


class InviteCreatedOut(BaseModel):
    invitation: InvitationOut
    email_queued: bool


class InvitationTokenIn(BaseModel):
    token: str = Field(min_length=1, max_length=MAX_TOKEN_LEN)


class InvitationInfoOut(BaseModel):
    """POST /auth/invitation (B04 D9): what the accept page shows."""

    email: str
    org_name: str
    role_key: str
    existing_account: bool  # true: ask for the CURRENT password, no name


class AcceptInviteIn(InvitationTokenIn):
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LEN)
    full_name: str | None = Field(default=None, max_length=MAX_NAME_LEN)

    @field_validator("full_name")
    @classmethod
    def _name(cls, v: str | None) -> str | None:
        return None if v is None or not v.strip() else _clean_name(v)


class AcceptedOut(BaseModel):
    status: str
    email: str
