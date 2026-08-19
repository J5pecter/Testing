from __future__ import annotations

import base64
import secrets
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.database import Database
from app.google_auth import (
    GoogleAuthorizationRequired,
    build_authorization_url,
    complete_authorization,
    connection_status,
)
from app.instagram import InstagramInputError, username_from_profile_url
from app.schemas import JobCreate
from app.services import PipelineRunner


class OptionalBasicAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not settings.app_password or request.url.path == "/api/auth/google/callback":
            return await call_next(request)
        header = request.headers.get("Authorization", "")
        valid = False
        if header.startswith("Basic "):
            try:
                encoded = header.split(" ", 1)[1]
                username, password = base64.b64decode(encoded).decode("utf-8").split(":", 1)
                valid = username == "admin" and secrets.compare_digest(password, settings.app_password)
            except (ValueError, UnicodeDecodeError):
                valid = False
        if valid:
            return await call_next(request)
        return FileResponse(
            settings.project_root / "app" / "static" / "unauthorized.html",
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": 'Basic realm="Instagram transfer"'},
        )


database = Database(settings.data_dir / "transfers.sqlite3")


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.initialize()
    app.state.executor = ThreadPoolExecutor(max_workers=settings.max_concurrent_jobs)
    yield
    app.state.executor.shutdown(wait=False, cancel_futures=False)


app = FastAPI(title="Instagram to YouTube Transfer", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    https_only=settings.app_base_url.startswith("https://"),
)
app.add_middleware(OptionalBasicAuthMiddleware)
app.mount("/static", StaticFiles(directory=settings.project_root / "app" / "static"), name="static")


@app.get("/", include_in_schema=False)
def home() -> FileResponse:
    return FileResponse(settings.project_root / "app" / "static" / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/settings/status")
def get_settings_status() -> dict[str, object]:
    return {
        "google": connection_status(),
        "instagram_login_required": False,
        "app_base_url": settings.app_base_url,
    }


@app.get("/api/auth/google/start")
def google_auth_start(request: Request) -> RedirectResponse:
    try:
        url, oauth_state = build_authorization_url()
    except GoogleAuthorizationRequired as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    request.session["google_oauth_state"] = oauth_state
    return RedirectResponse(url)


@app.get("/api/auth/google/callback")
def google_auth_callback(request: Request, state: str | None = None, error: str | None = None) -> RedirectResponse:
    if error:
        return RedirectResponse(url="/?google_error=denied")
    expected_state = request.session.pop("google_oauth_state", None)
    if not state or not expected_state or not secrets.compare_digest(state, expected_state):
        raise HTTPException(status_code=400, detail="Google OAuth state did not match. Try connecting again.")
    try:
        complete_authorization(str(request.url), state)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Google authorization failed: {exc}") from exc
    return RedirectResponse(url="/?google_connected=1")


@app.get("/api/jobs")
def list_jobs() -> list[dict[str, object]]:
    return database.list_jobs()


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, object]:
    job = database.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return {"job": job, "videos": database.list_videos(job_id)}


@app.post("/api/jobs", status_code=202)
def create_job(payload: JobCreate, request: Request) -> dict[str, object]:
    if not connection_status()["connected"]:
        raise HTTPException(status_code=400, detail="Connect Google Drive and YouTube before starting a job.")
    try:
        username = username_from_profile_url(str(payload.profile_url))
    except InstagramInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    job = database.create_job(
        profile_url=str(payload.profile_url),
        username=username,
        privacy=payload.privacy,
        max_videos=payload.max_videos,
    )
    request.app.state.executor.submit(PipelineRunner(database).run, job["id"])
    return job


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict[str, str]:
    job = database.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job["status"] not in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="Only queued or running jobs can be cancelled.")
    database.update_job(job_id, cancel_requested=1, message="Cancellation requested…")
    return {"message": "Cancellation requested."}
