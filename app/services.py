from __future__ import annotations

import mimetypes
import re
import shutil
from pathlib import Path
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from app.config import settings
from app.database import Database, now
from app.google_auth import get_credentials
from app.instagram import DownloadedVideo, PublicInstagramDownloader


def make_title(caption: str, *, fallback: str) -> str:
    cleaned = re.sub(r"https?://\S+", "", caption)
    cleaned = re.sub(r"#[\w_]+", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -–—|.,")
    if not cleaned:
        return fallback
    if len(cleaned) <= 100:
        return cleaned
    return f"{cleaned[:99].rstrip()}…"


def make_description(caption: str, source_url: str) -> str:
    text = caption.strip()
    attribution = f"\n\nOriginal Instagram post: {source_url}"
    return (text[:4_800] + attribution)[:5_000]


def make_tags(caption: str) -> list[str]:
    tags = [tag.lower() for tag in re.findall(r"#([\w_]+)", caption)]
    unique = list(dict.fromkeys(["instagram", *tags]))
    return [tag[:30] for tag in unique[:20]]


class PipelineRunner:
    def __init__(self, database: Database) -> None:
        self.database = database

    def run(self, job_id: str) -> None:
        job = self.database.get_job(job_id)
        if not job:
            return
        self.database.update_job(job_id, status="running", started_at=now(), message="Checking Google access…")
        try:
            credentials = get_credentials()
            drive = build("drive", "v3", credentials=credentials, cache_discovery=False)
            youtube = build("youtube", "v3", credentials=credentials, cache_discovery=False)
            destination = settings.data_dir / "jobs" / job_id
            downloaded = self._download(job, destination)
            if self.database.cancel_requested(job_id):
                self._cancel(job_id)
                return
            if not downloaded:
                self.database.update_job(
                    job_id,
                    status="succeeded",
                    message="No public video posts were found.",
                    completed_at=now(),
                )
                return
            for item in downloaded:
                self._create_video(job_id, item)
            job = self.database.get_job(job_id) or job
            folder_id = job["drive_folder_id"] or self._create_drive_folder(drive, job)
            if not job["drive_folder_id"]:
                self.database.update_job(job_id, drive_folder_id=folder_id)
            for video in self.database.list_videos(job_id):
                if self.database.cancel_requested(job_id):
                    self._cancel(job_id)
                    return
                self._process_video(drive, youtube, job, folder_id, video)
            videos = self.database.list_videos(job_id)
            has_problems = any(video["status"] != "complete" for video in videos)
            self.database.update_job(
                job_id,
                status="partial" if has_problems else "succeeded",
                message=("Finished with items needing attention." if has_problems else "All videos transferred successfully."),
                completed_at=now(),
            )
        except Exception as exc:  # preserve a useful job-level failure in the UI
            self.database.update_job(
                job_id, status="failed", error=str(exc), message="Job stopped.", completed_at=now()
            )

    def _download(self, job: dict[str, Any], destination: Path) -> list[DownloadedVideo]:
        downloader = PublicInstagramDownloader()

        def progress(message: str) -> None:
            self.database.update_job(job["id"], message=message)

        self.database.update_job(job["id"], message="Reading public Instagram posts…")
        return downloader.download_all(
            profile_url=job["profile_url"],
            destination=destination,
            max_videos=job["max_videos"],
            is_cancelled=lambda: self.database.cancel_requested(job["id"]),
            progress=progress,
        )

    def _create_video(self, job_id: str, item: DownloadedVideo) -> None:
        fallback = f"Instagram video {item.shortcode}"
        self.database.create_video(
            job_id,
            source_shortcode=item.shortcode,
            source_url=item.source_url,
            caption=item.caption,
            title=make_title(item.caption, fallback=fallback),
            description=make_description(item.caption, item.source_url),
            local_path=str(item.path.resolve()),
        )

    def _create_drive_folder(self, drive: Any, job: dict[str, Any]) -> str:
        self.database.update_job(job["id"], message="Creating Google Drive folder…")
        result = drive.files().create(
            body={
                "name": f"Instagram transfer — {job['username']} — {job['id'][:8]}",
                "mimeType": "application/vnd.google-apps.folder",
            },
            fields="id",
        ).execute()
        return result["id"]

    def _process_video(
        self, drive: Any, youtube: Any, job: dict[str, Any], folder_id: str, video: dict[str, Any]
    ) -> None:
        path = Path(video["local_path"])
        if not path.is_file():
            self.database.update_video(video["id"], status="failed", error="Downloaded file is missing.")
            return
        try:
            if not video["drive_file_id"]:
                self.database.update_job(job["id"], message=f"Uploading {path.name} to Google Drive…")
                drive_file_id = self._upload_to_drive(drive, folder_id, path)
                self.database.update_video(video["id"], drive_file_id=drive_file_id, status="in_drive")
                video["drive_file_id"] = drive_file_id
            if not video["youtube_video_id"]:
                self.database.update_job(job["id"], message=f"Uploading {path.name} to YouTube…")
                youtube_id = self._upload_to_youtube(youtube, job["privacy"], video, path)
                self.database.update_video(video["id"], youtube_video_id=youtube_id, status="youtube_uploaded")
                video["youtube_video_id"] = youtube_id
            self.database.update_job(job["id"], message=f"Deleting {path.name} from Google Drive…")
            drive.files().delete(fileId=video["drive_file_id"]).execute()
            self.database.update_video(video["id"], status="complete", error=None)
            if settings.delete_local_after_success:
                path.unlink(missing_ok=True)
        except Exception as exc:
            self.database.update_video(video["id"], status="failed", error=str(exc))

    @staticmethod
    def _upload_to_drive(drive: Any, folder_id: str, path: Path) -> str:
        mime_type = mimetypes.guess_type(path.name)[0] or "video/mp4"
        media = MediaFileUpload(str(path), mimetype=mime_type, resumable=True)
        request = drive.files().create(
            body={"name": path.name, "parents": [folder_id]}, media_body=media, fields="id"
        )
        response = None
        while response is None:
            _, response = request.next_chunk()
        return response["id"]

    @staticmethod
    def _upload_to_youtube(youtube: Any, privacy: str, video: dict[str, Any], path: Path) -> str:
        media = MediaFileUpload(str(path), mimetype="video/mp4", resumable=True)
        request = youtube.videos().insert(
            part="snippet,status",
            body={
                "snippet": {
                    "title": video["title"],
                    "description": video["description"],
                    "tags": make_tags(video["caption"]),
                    "categoryId": "22",
                },
                "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False},
            },
            media_body=media,
        )
        response = None
        while response is None:
            _, response = request.next_chunk()
        return response["id"]

    def _cancel(self, job_id: str) -> None:
        self.database.update_job(job_id, status="cancelled", message="Cancelled by user.", completed_at=now())
