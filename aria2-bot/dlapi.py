"""Client for the dlapi.yebekhe.workers.dev multi-service downloader API.

Fetches download links server-side, so the bot never talks to YouTube
directly and avoids yt-dlp bot-detection. Returns direct URLs that the
bot downloads with aria2.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re

logger = logging.getLogger("aria2bot.dlapi")

BASE_URL = "https://dlapi.yebekhe.workers.dev"

VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".flv"}
AUDIO_EXTS = {".mp3", ".m4a", ".aac", ".wav", ".flac", ".opus", ".weba"}


async def _get(path: str, params: dict, timeout: float = 30.0) -> dict:
    import urllib.parse
    from urllib.request import Request, urlopen

    query = urllib.parse.urlencode(params)
    url = f"{BASE_URL}{path}?{query}"
    loop = asyncio.get_event_loop()

    def fetch():
        req = Request(url, headers={"User-Agent": "Mozilla/5.0 (Telegram Downloader Bot)"})
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    return await loop.run_in_executor(None, fetch)


def _ext_from_url(url: str) -> str:
    match = re.search(r"\.([A-Za-z0-9]{2,5})(?:\?|$)", url)
    if match:
        ext = match.group(1).lower()
        if ext in {"mp4", "mkv", "webm", "mov", "avi", "flv", "mp3", "m4a", "aac", "wav", "flac", "opus", "weba"}:
            return ext
    return "mp4"


async def fetch_youtube(url: str) -> dict | None:
    """Query the /youtube endpoint. Returns the parsed JSON or None on failure."""
    try:
        data = await _get("/youtube", {"url": url})
    except Exception as e:
        logger.info("dlapi /youtube failed: %s", e)
        return None
    if not data or not data.get("success"):
        logger.info("dlapi /youtube unsupported: %s", (data or {}).get("error"))
        return None
    return data


def build_options(data: dict) -> list[dict]:
    """Build the format-selection menu from a dlapi /youtube response."""
    options: list[dict] = []
    video_links = data.get("videoLinks") or []
    audio_links = data.get("audioLinks") or []

    def add_video(entry: dict, index: int):
        quality = entry.get("quality") or f"Format {index + 1}"
        size = entry.get("size") or ""
        url = entry.get("url")
        if not url:
            return
        label = f"🎬 {quality}"
        if size:
            label += f" · {size}"
        options.append(
            {
                "option_id": f"dlv{len(options)}",
                "label": label,
                "send_type": "video",
                "mode": "dlapi_download",
                "url": url,
                "file_ext": _ext_from_url(url),
            }
        )

    def add_audio(entry: dict):
        quality = entry.get("quality") or "Audio"
        size = entry.get("size") or ""
        url = entry.get("url")
        if not url:
            return
        label = f"🎵 {quality}"
        if size:
            label += f" · {size}"
        options.append(
            {
                "option_id": f"dla{len(options)}",
                "label": label,
                "send_type": "audio",
                "mode": "dlapi_download",
                "url": url,
                "file_ext": _ext_from_url(url),
            }
        )

    for i, entry in enumerate(video_links[:12]):
        add_video(entry, i)
    for entry in audio_links[:6]:
        add_audio(entry)
    return options


def build_audio_options(data: dict) -> list[dict]:
    """Quick MP3-style options if only audio matters (fallback path)."""
    audio_links = data.get("audioLinks") or []
    options = []
    for entry in audio_links[:6]:
        quality = entry.get("quality") or "Audio"
        url = entry.get("url")
        if not url:
            continue
        options.append(
            {
                "option_id": f"dla{len(options)}",
                "label": f"🎵 {quality}",
                "send_type": "audio",
                "mode": "dlapi_download",
                "url": url,
                "file_ext": _ext_from_url(url),
            }
        )
    return options
