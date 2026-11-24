"""RBAC response/request models (design B04 §3.5, api_spec.md §5)."""

from pydantic import BaseModel, Field


class RoleOut(BaseModel):
    key: str
    name: str
    priority: int
    landing_path: str
    is_system: bool
    permissions: list[str]


class PermissionOut(BaseModel):
    key: str
    module: str
    description: str | None


class RoleKeysIn(BaseModel):
    role_keys: list[str] = Field(max_length=20)
