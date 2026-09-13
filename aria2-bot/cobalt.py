"""Client for a self-hosted cobalt instance (https://github.com/imputnet/cobalt).

Cobalt is a media downloader that works like a fancy proxy: you POST a
source URL, and cobalt fetches the media on its own servers and either
tunnels (proxies) the file back or gives you a direct/redirect URL. Because
the fetch happens on the cobalt server, the bot's IP is never seen by
YouTube, so bot-detection is completely bypassed.

API: POST {COBALT_API_URL}/  with JSON body { url, videoQuality, ... }
Returns a JSON body with status "tunnel" | "redirect" | "picker" | "error".

The public api.cobalt.tools is bot-protected and not meant for other
projects — self-host your own instance (docker compose) and set COBALT_API_URL.
"""

from __future__ import annotations

import asyncio
import json
import logging
from urllib.request import Request, urlopen

logger = logging.getLogger("aria2bot.cobalt")

# (videoQuality, label, ext, send_type)
VIDEO_QUALITIES = [
    ("1080", "🎬 1080p (mp4)", "mp4", "video"),
    ("720", "🎬 720p (mp4)", "mp4", "video"),
    ("480", "🎬 480p (mp4)", "mp4", "video"),
    ("360", "🎬 360p (mp4)", "mp4", "video"),
]

# (audioBitrate, label, ext, send_type)
AUDIO_BITRATES = [
    ("320", "🎵 MP3 (320k)", "mp3", "audio"),
    ("128", "🎵 MP3 (128k)", "mp3", "audio"),
]


async def _post(base_url: str, body: dict, timeout: float = 60.0) -> dict:
    loop = asyncio.get_event_loop()

    def fetch():
        data = json.dumps(body).encode("utf-8")
        req = Request(
            f"{base_url}/",
            data=data,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Telegram Downloader Bot)",
            },
            method="POST",
        )
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    return await loop.run_in_executor(None, fetch)


async def fetch_one(base_url: str, url: str, quality: str, audio: bool) -> dict | None:
    """Ask cobalt for a single download link at the given quality."""
    body = {
        "url": url,
        "videoQuality": quality,
        "audioBitrate": "128",
        "audioFormat": "mp3",
        "filenameStyle": "pretty",
        "disableMetadata": False,
        "alwaysProxy": True,
        "youtubeVideoCodec": "h264",
        "youtubeVideoContainer": "mp4",
        "youtubeBetterAudio": True,
    }
    if audio:
        body["downloadMode"] = "audio"
        body["audioBitrate"] = quality
    try:
        data = await _post(base_url, body)
    except Exception as e:
        logger.info("cobalt request failed: %s", e)
        return None
    return data


def _link_from(data: dict) -> str | None:
    """Extract a downloadable URL from a cobalt response (tunnel/redirect/local-processing)."""
    status = data.get("status")
    if status == "tunnel" or status == "redirect":
        return data.get("url")
    if status == "local-processing":
        tunnels = data.get("tunnel") or []
        return tunnels[0] if tunnels else None
    return None


async def build_options(base_url: str, url: str) -> list[dict]:
    """Build a format-selection menu by probing several qualities/bitrates.

    Returns [] when the instance is unreachable or the video is unavailable.
    """
    options: list[dict] = []
    seen: set[str] = set()
    for quality, label, ext, send_type in VIDEO_QUALITIES + AUDIO_BITRATES:
        audio = send_type == "audio"
        data = await fetch_one(base_url, url, quality, audio)
        if not data:
            continue
        if data.get("status") == "picker":
            for item in (data.get("picker") or [])[:6]:
                item_url = item.get("url")
                if not item_url or item_url in seen:
                    continue
                seen.add(item_url)
                options.append(
                    {
                        "option_id": f"cob{len(options)}",
                        "label": f"🎞️ Media {len(options) + 1}",
                        "send_type": "video" if item.get("type") == "video" else "document",
                        "mode": "dlapi_download",
                        "url": item_url,
                        "file_ext": "mp4",
                    }
                )
            break
        if data.get("status") == "error":
            code = (data.get("error") or {}).get("code", "unknown")
            logger.info("cobalt error %s: %s", code, data)
            continue
        link = _link_from(data)
        if not link or link in seen:
            continue
        seen.add(link)
        filename = data.get("filename") or f"cobalt.{ext}"
        options.append(
            {
                "option_id": f"cob{len(options)}",
                "label": label,
                "send_type": send_type,
                "mode": "dlapi_download",
                "url": link,
                "file_ext": ext,
                "file_name": filename,
            }
        )
    return options
