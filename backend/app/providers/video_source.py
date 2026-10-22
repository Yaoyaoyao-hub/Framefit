"""Download a public video so the browser can pick one frame.

YouTube, TikTok, and direct video links are not video files the browser can
play and capture. The file is returned to the browser and is not stored.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.errors import APIError, ProviderError
from app.ssrf import assert_public_url

MAX_VIDEO_BYTES = 40_000_000


def download_video(url: str) -> tuple[bytes, str]:
    cleaned = url.strip()
    if len(cleaned) > 500:
        raise APIError(400, "invalid_link", "That video link is too long.")
    try:
        assert_public_url(cleaned)
    except ProviderError as exc:
        raise APIError(400, "invalid_link", "That video address cannot be used.") from exc
    try:
        import yt_dlp
    except ImportError as exc:
        raise APIError(503, "video_unavailable", "Video links are unavailable until the video downloader is installed.") from exc

    with tempfile.TemporaryDirectory(prefix="framefit-video-") as folder:
        dest = Path(folder)
        options = {
            "format": "b[height<=720]/b",
            "outtmpl": str(dest / "source.%(ext)s"),
            "noplaylist": True,
            "max_filesize": MAX_VIDEO_BYTES,
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "socket_timeout": 30,
            "retries": 1,
            "restrictfilenames": True,
        }
        try:
            with yt_dlp.YoutubeDL(options) as downloader:
                downloader.download([cleaned])
        except Exception as exc:
            raise APIError(
                400,
                "video_unavailable",
                "That video could not be opened. Use a public YouTube, TikTok, or direct video link.",
            ) from exc
        files = [path for path in dest.rglob("*") if path.is_file() and path.suffix not in {".part", ".ytdl"}]
        if not files:
            raise APIError(400, "video_unavailable", "That video could not be opened. Use a public YouTube, TikTok, or direct video link.")
        chosen = max(files, key=lambda path: path.stat().st_size)
        size = chosen.stat().st_size
        if size > MAX_VIDEO_BYTES:
            raise APIError(400, "video_too_large", "That video is too large to open here.")
        if size < 1000:
            raise APIError(400, "video_unavailable", "That video could not be opened. Use a public YouTube, TikTok, or direct video link.")
        media = "video/webm" if chosen.suffix.lower() == ".webm" else "video/mp4"
        return chosen.read_bytes(), media
