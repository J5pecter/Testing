from __future__ import annotations

from pydantic import BaseModel, Field, HttpUrl, field_validator


class JobCreate(BaseModel):
    profile_url: HttpUrl
    privacy: str = Field(default="private", pattern="^(private|unlisted|public)$")
    max_videos: int = Field(default=0, ge=0, le=5_000)
    rights_confirmed: bool

    @field_validator("rights_confirmed")
    @classmethod
    def must_confirm_rights(cls, value: bool) -> bool:
        if not value:
            raise ValueError("Confirm that you own or are licensed to republish the videos.")
        return value
