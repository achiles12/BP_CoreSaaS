"""Files request/response models (design B05 §3.4, api_spec.md §6).

Pydantic checks only the shape. The size limit (413), the MIME allowlist (415)
and the file-name cleaning (422) live in service.py, because they depend on
settings and need their own error codes (D5).
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

# Raw input bound; the cleaned name must be <= MAX_FILE_NAME_LEN (service.clean_name).
MAX_RAW_NAME_LEN = 1024
MAX_MIME_LEN = 255


class PresignIn(BaseModel):
    name: str = Field(min_length=1, max_length=MAX_RAW_NAME_LEN, description="original file name")
    mime_type: str = Field(min_length=3, max_length=MAX_MIME_LEN, examples=["application/pdf"])
    size_bytes: int = Field(gt=0, description="exact size the browser will upload")

    @field_validator("mime_type")
    @classmethod
    def _norm_mime(cls, v: str) -> str:
        # "Application/PDF; charset=x" -> "application/pdf": parameters are not
        # part of the allowlist and would break the signed Content-Type.
        return v.split(";")[0].strip().lower()


class PresignOut(BaseModel):
    file_id: uuid.UUID
    upload_url: str
    # Headers the client MUST send with the PUT (Content-Type is signed, D6).
    headers: dict[str, str]
    expires_in: int


class FileOut(BaseModel):
    id: uuid.UUID
    name: str
    mime_type: str
    size_bytes: int
    status: str
    uploaded_by: uuid.UUID
    uploader_name: str | None  # D13: public.users.full_name (may be unset)
    created_at: datetime


class DownloadOut(BaseModel):
    url: str
    expires_in: int
