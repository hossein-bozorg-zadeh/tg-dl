"""Client for a Koutube instance (https://github.com/iGerman00/koutube).

Koutube proxies YouTube through Invidious and exposes a JSON API that
returns direct download links. Because the link is generated on another
server, the bot never talks to YouTube directly and avoids yt-dlp
bot-detection ("Sign in to confirm you're not a bot").

API: GET {base}/api/watch?v={video_id}&direct&itag={itag}
Returns JSON with a "playerStreamUrl" pointing at the media file.

You can self-host Koutube (Cloudflare Workers + D1) and set the base URL,
or use the public instance at https://koutu.be
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import urllib.parse
from urllib.request import Request, urlopen

logger = logging.getLogger("aria2bot.koutube")

# itag -> (label, extension, send_type)
ITAGS = [
    (22, "🎬 720p (mp4)", "mp4", "video"),
    (18, "🎬 360p (mp4)", "mp4", "video"),
    (140, "🎵 Audio (m4a)", "m4a", "audio"),
    (251, "🎵 Audio (opus)", "opus", "audio"),
]


def extract_video_id(url: str) -> str | None:
    """Pull the video id from any common YouTube URL form."""
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return None
    if "youtu.be" in parsed.netloc:
        return parsed.path.strip("/").split("/")[0] or None
    query = urllib.parse.parse_qs(parsed.query)
    if "v" in query:
        return query["v"][0]
    parts = parsed.path.strip("/").split("/")
    if len(parts) > 1 and parts[0] in ("shorts", "embed", "v"):
        return parts[1]
    return None


async def _get(base_url: str, path: str, params: dict, timeout: float = 30.0) -> dict:
    query = urllib.parse.urlencode(params)
    url = f"{base_url}{path}?{query}"
    loop = asyncio.get_event_loop()

    def fetch():
        req = Request(url, headers={"User-Agent": "Mozilla/5.0 (Telegram Downloader Bot)"})
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    return await loop.run_in_executor(None, fetch)


async def fetch_direct(base_url: str, video_id: str, itag: int) -> str | None:
    """Ask koutube for a direct download URL at the given itag."""
    try:
        data = await _get(base_url, "/api/watch", {"v": video_id, "direct": "", "itag": str(itag)})
    except Exception as e:
        logger.info("koutube itag %s failed: %s", itag, e)
        return None
    url = (data or {}).get("playerStreamUrl")
    if not url:
        return None
    return str(url)


async def build_options(base_url: str, url: str) -> list[dict]:
    """Build a format-selection menu by querying a few common itags.

    Returns [] when the instance is unreachable or the video is unavailable.
    """
    video_id = extract_video_id(url)
    if not video_id:
        return []
    options: list[dict] = []
    for itag, label, ext, send_type in ITAGS:
        direct = await fetch_direct(base_url, video_id, itag)
        if not direct:
            continue
        options.append(
            {
                "option_id": f"kot{itag}",
                "label": label,
                "send_type": send_type,
                "mode": "dlapi_download",
                "url": direct,
                "file_ext": ext,
            }
        )
    return options
