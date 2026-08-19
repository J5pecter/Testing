from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    project_root: Path
    data_dir: Path
    app_base_url: str
    session_secret: str
    google_client_secrets: Path
    google_client_secrets_b64: str | None
    google_token_file: Path
    app_password: str | None
    max_concurrent_jobs: int
    delete_local_after_success: bool

    @property
    def google_redirect_url(self) -> str:
        return f"{self.app_base_url.rstrip('/')}/api/auth/google/callback"


def _from_env_path(name: str, default: str) -> Path:
    raw = Path(os.getenv(name, default))
    return raw if raw.is_absolute() else PROJECT_ROOT / raw


settings = Settings(
    project_root=PROJECT_ROOT,
    data_dir=_from_env_path("APP_DATA_DIR", "data"),
    app_base_url=os.getenv("APP_BASE_URL", "http://127.0.0.1:8000").rstrip("/"),
    session_secret=os.getenv("SESSION_SECRET", "development-only-change-this-secret"),
    google_client_secrets=_from_env_path("GOOGLE_CLIENT_SECRETS", "client_secret.json"),
    google_client_secrets_b64=os.getenv("GOOGLE_CLIENT_SECRETS_B64") or None,
    google_token_file=_from_env_path("GOOGLE_TOKEN_FILE", "data/google_token.json"),
    app_password=os.getenv("APP_PASSWORD") or None,
    max_concurrent_jobs=max(1, int(os.getenv("MAX_CONCURRENT_JOBS", "1"))),
    delete_local_after_success=_as_bool(os.getenv("DELETE_LOCAL_AFTER_SUCCESS"), True),
)
