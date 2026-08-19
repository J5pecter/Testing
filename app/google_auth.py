from __future__ import annotations

import base64
import binascii
import json
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from app.config import settings


SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/youtube.upload",
]


class GoogleAuthorizationRequired(RuntimeError):
    pass


def client_secrets_path() -> Path | None:
    """Return a local OAuth-client JSON file, materialising a production secret if set."""
    if settings.google_client_secrets.is_file():
        return settings.google_client_secrets
    if not settings.google_client_secrets_b64:
        return None
    try:
        contents = base64.b64decode(settings.google_client_secrets_b64, validate=True)
        parsed = json.loads(contents)
        if not isinstance(parsed, dict) or not ({"web", "installed"} & parsed.keys()):
            raise ValueError("not a Google OAuth client JSON file")
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise GoogleAuthorizationRequired("GOOGLE_CLIENT_SECRETS_B64 is not valid OAuth client JSON.") from exc
    destination = settings.data_dir / "google_oauth_client.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(contents)
    return destination


def client_is_configured() -> bool:
    try:
        return client_secrets_path() is not None
    except GoogleAuthorizationRequired:
        return False


def build_authorization_url() -> tuple[str, str]:
    secrets_path = client_secrets_path()
    if not secrets_path:
        raise GoogleAuthorizationRequired(
            "Add the Google OAuth client JSON at the GOOGLE_CLIENT_SECRETS path first."
        )
    flow = Flow.from_client_secrets_file(
        str(secrets_path), scopes=SCOPES, redirect_uri=settings.google_redirect_url
    )
    url, state = flow.authorization_url(
        access_type="offline", include_granted_scopes="true", prompt="consent"
    )
    return url, state


def complete_authorization(authorization_response: str, state: str) -> None:
    secrets_path = client_secrets_path()
    if not secrets_path:
        raise GoogleAuthorizationRequired("Google OAuth client configuration is missing.")
    flow = Flow.from_client_secrets_file(
        str(secrets_path),
        scopes=SCOPES,
        state=state,
        redirect_uri=settings.google_redirect_url,
    )
    flow.fetch_token(authorization_response=authorization_response)
    settings.google_token_file.parent.mkdir(parents=True, exist_ok=True)
    settings.google_token_file.write_text(flow.credentials.to_json(), encoding="utf-8")


def get_credentials() -> Credentials:
    token_path: Path = settings.google_token_file
    if not token_path.is_file():
        raise GoogleAuthorizationRequired("Connect Google Drive and YouTube before starting a job.")
    credentials = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        token_path.write_text(credentials.to_json(), encoding="utf-8")
    if not credentials.valid:
        raise GoogleAuthorizationRequired("Google authorization expired. Connect Google again.")
    return credentials


def connection_status() -> dict[str, bool]:
    if not client_is_configured():
        return {"client_configured": False, "connected": False}
    try:
        get_credentials()
        return {"client_configured": True, "connected": True}
    except GoogleAuthorizationRequired:
        return {"client_configured": True, "connected": False}
