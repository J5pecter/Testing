from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    profile_url TEXT NOT NULL,
                    username TEXT NOT NULL,
                    privacy TEXT NOT NULL,
                    max_videos INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    message TEXT,
                    error TEXT,
                    drive_folder_id TEXT,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT
                );
                CREATE TABLE IF NOT EXISTS videos (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    source_shortcode TEXT,
                    source_url TEXT,
                    caption TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    local_path TEXT NOT NULL,
                    drive_file_id TEXT,
                    youtube_video_id TEXT,
                    status TEXT NOT NULL,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_videos_job_id ON videos(job_id);
                """
            )

    def create_job(
        self, *, profile_url: str, username: str, privacy: str, max_videos: int
    ) -> dict[str, Any]:
        job_id = str(uuid.uuid4())
        created = now()
        with self._connection() as con:
            con.execute(
                """INSERT INTO jobs
                (id, profile_url, username, privacy, max_videos, status, created_at)
                VALUES (?, ?, ?, ?, ?, 'queued', ?)""",
                (job_id, profile_url, username, privacy, max_videos, created),
            )
        return self.get_job(job_id)  # type: ignore[return-value]

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._connection() as con:
            row = con.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._job_dict(row) if row else None

    def list_jobs(self) -> list[dict[str, Any]]:
        with self._connection() as con:
            rows = con.execute(
                """SELECT j.*, COUNT(v.id) AS video_count,
                   SUM(CASE WHEN v.status = 'complete' THEN 1 ELSE 0 END) AS completed_count
                   FROM jobs j LEFT JOIN videos v ON v.job_id = j.id
                   GROUP BY j.id ORDER BY j.created_at DESC"""
            ).fetchall()
        return [self._job_dict(row) for row in rows]

    def update_job(self, job_id: str, **changes: Any) -> None:
        allowed = {
            "status", "message", "error", "drive_folder_id", "cancel_requested",
            "started_at", "completed_at",
        }
        values = {key: value for key, value in changes.items() if key in allowed}
        if not values:
            return
        assignments = ", ".join(f"{key} = ?" for key in values)
        with self._connection() as con:
            con.execute(
                f"UPDATE jobs SET {assignments} WHERE id = ?",
                (*values.values(), job_id),
            )

    def cancel_requested(self, job_id: str) -> bool:
        with self._connection() as con:
            row = con.execute(
                "SELECT cancel_requested FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return bool(row and row["cancel_requested"])

    def create_video(self, job_id: str, **video: Any) -> dict[str, Any]:
        video_id = str(uuid.uuid4())
        timestamp = now()
        with self._connection() as con:
            con.execute(
                """INSERT INTO videos
                (id, job_id, source_shortcode, source_url, caption, title, description,
                 local_path, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'downloaded', ?, ?)""",
                (
                    video_id,
                    job_id,
                    video.get("source_shortcode"),
                    video.get("source_url"),
                    video.get("caption", ""),
                    video["title"],
                    video.get("description", ""),
                    video["local_path"],
                    timestamp,
                    timestamp,
                ),
            )
        return self.get_video(video_id)  # type: ignore[return-value]

    def get_video(self, video_id: str) -> dict[str, Any] | None:
        with self._connection() as con:
            row = con.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()
        return self._video_dict(row) if row else None

    def list_videos(self, job_id: str) -> list[dict[str, Any]]:
        with self._connection() as con:
            rows = con.execute(
                "SELECT * FROM videos WHERE job_id = ? ORDER BY created_at", (job_id,)
            ).fetchall()
        return [self._video_dict(row) for row in rows]

    def update_video(self, video_id: str, **changes: Any) -> None:
        allowed = {"status", "drive_file_id", "youtube_video_id", "error", "local_path"}
        values = {key: value for key, value in changes.items() if key in allowed}
        if not values:
            return
        values["updated_at"] = now()
        assignments = ", ".join(f"{key} = ?" for key in values)
        with self._connection() as con:
            con.execute(
                f"UPDATE videos SET {assignments} WHERE id = ?",
                (*values.values(), video_id),
            )

    @staticmethod
    def _job_dict(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["cancel_requested"] = bool(item["cancel_requested"])
        return item

    @staticmethod
    def _video_dict(row: sqlite3.Row) -> dict[str, Any]:
        return dict(row)
