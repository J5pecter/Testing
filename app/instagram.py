from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


RESERVED_PATHS = {
    "accounts", "about", "developer", "direct", "explore", "p", "reel", "reels",
    "stories", "web", "api", "oauth", "challenge",
}
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9._]{1,30}$")


class InstagramInputError(ValueError):
    pass


@dataclass(frozen=True)
class DownloadedVideo:
    path: Path
    shortcode: str
    source_url: str
    caption: str


def username_from_profile_url(profile_url: str) -> str:
    parsed = urlparse(profile_url)
    host = parsed.hostname.lower() if parsed.hostname else ""
    if host not in {"instagram.com", "www.instagram.com", "m.instagram.com"}:
        raise InstagramInputError("Use a public instagram.com profile URL.")
    segments = [part for part in parsed.path.split("/") if part]
    if len(segments) != 1:
        raise InstagramInputError("Use a profile URL such as https://www.instagram.com/username/.")
    username = segments[0].lstrip("@").lower()
    if username in RESERVED_PATHS or not USERNAME_PATTERN.fullmatch(username):
        raise InstagramInputError("That does not look like an Instagram profile username.")
    return username


class PublicInstagramDownloader:
    """Download only media Instagram exposes without an authenticated account."""

    def download_all(
        self,
        *,
        profile_url: str,
        destination: Path,
        max_videos: int,
        is_cancelled: callable,
        progress: callable,
    ) -> list[DownloadedVideo]:
        try:
            import instaloader
        except ImportError as exc:  # pragma: no cover - dependency install issue
            raise RuntimeError("instaloader is not installed. Run pip install -r requirements.txt.") from exc

        username = username_from_profile_url(profile_url)
        destination.mkdir(parents=True, exist_ok=True)
        loader = instaloader.Instaloader(
            dirname_pattern=str(destination / "{target}"),
            filename_pattern="{date_utc}_UTC_{shortcode}",
            download_pictures=False,
            download_videos=True,
            download_video_thumbnails=False,
            download_geotags=False,
            download_comments=False,
            save_metadata=False,
            compress_json=False,
            post_metadata_txt_pattern="",
            quiet=True,
        )
        try:
            profile = instaloader.Profile.from_username(loader.context, username)
            videos: list[DownloadedVideo] = []
            profile_dir = destination / username
            for post_number, post in enumerate(profile.get_posts(), start=1):
                if is_cancelled():
                    break
                has_video = post.is_video or (
                    post.typename == "GraphSidecar"
                    and any(node.is_video for node in post.get_sidecar_nodes())
                )
                if not has_video:
                    continue
                progress(f"Downloading Instagram video {len(videos) + 1} (post {post_number})…")
                prior_paths = {file.resolve() for file in profile_dir.glob("*.mp4")} if profile_dir.exists() else set()
                loader.download_post(post, target=username)
                downloaded_paths = sorted(
                    file for file in profile_dir.glob("*.mp4") if file.resolve() not in prior_paths
                )
                for path in downloaded_paths:
                    videos.append(
                        DownloadedVideo(
                            path=path,
                            shortcode=post.shortcode,
                            source_url=f"https://www.instagram.com/p/{post.shortcode}/",
                            caption=post.caption or "",
                        )
                    )
                    if max_videos and len(videos) >= max_videos:
                        return videos
            return videos
        finally:
            loader.close()
