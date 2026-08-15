import asyncio
import logging
import os
import re
import subprocess
import urllib.parse

import aiohttp

import config
from aria2_client import Aria2Client

logger = logging.getLogger("aria2bot.downloaders")

MEGA_RE = re.compile(r"https?://(?:www\.|mega\.|mega\.nz/)?mega\.nz/(?:file|folder)/[^#\s]+(?:#[^\s]+)?", re.I)
MEDIAFIRE_RE = re.compile(r"https?://(?:www\.)?mediafire\.com/(?:file|view|folder|download)/\S+", re.I)


def detect(url: str) -> str:
    if MEGA_RE.search(url):
        return "mega"
    if MEDIAFIRE_RE.search(url):
        return "mediafire"
    return "aria2"


async def resolve_mediafire(url: str) -> str:
    async with aiohttp.ClientSession() as session:
        async with session.get(url, allow_redirects=True) as resp:
            html = await resp.text()
    m = re.search(r'<a\s+[^>]*id="downloadButton"[^>]*href="([^"]+)"', html, re.I)
    if not m:
        m = re.search(r"aria:download\s*=\s*['\"]([^'\"]+)['\"]", html, re.I)
    if not m:
        m = re.search(r"href=\"(https?://download[^\"]+)\"", html, re.I)
    if not m:
        raise RuntimeError("Could not extract a direct download link from the MediaFire page")
    link = m.group(1).replace("&amp;", "&")
    if link.startswith("/"):
        link = urllib.parse.urljoin("https://www.mediafire.com", link)
    return link


async def download_with_aria2(aria2: Aria2Client, url: str, dir_path: str) -> tuple[str, int]:
    gid = await aria2.add_uri([url], {"dir": dir_path})
    return gid, 0


async def wait_aria2(aria2: Aria2Client, gid: str, progress_cb=None, interval: float = 1.0) -> dict:
    while True:
        st = await aria2.get_status(gid)
        status = st.get("status")
        if progress_cb:
            await progress_cb(
                int(st.get("completedLength") or 0),
                int(st.get("totalLength") or 0),
                int(st.get("downloadSpeed") or 0),
            )
        if status in ("complete", "error", "removed"):
            return st
        await asyncio.sleep(interval)


async def download_mega(url: str, dir_path: str, progress_cb=None) -> tuple[str, int]:
    os.makedirs(dir_path, exist_ok=True)
    cmd = ["megadl", "--path", dir_path, url]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    assert proc.stdout is not None
    size = 0
    name = ""
    while True:
        line = await proc.stdout.readline()
        if not line:
            break
        text = line.decode(errors="replace").strip()
        if not text:
            continue
        logger.debug("megadl: %s", text)
        m = re.search(r"([\d.]+) %", text)
        if m:
            pct = float(m.group(1))
            if progress_cb and size > 0:
                await progress_cb(int(size * pct / 100.0), size, 0)
        m = re.search(r"Filename:\s*(.+)", text)
        if m:
            name = m.group(1).strip()
        m = re.search(r"Download (?:file|finished)", text, re.I)
        if m:
            pass
        # megatools prints nothing about total; detect via file after completion
    code = await proc.wait()
    if code != 0:
        raise RuntimeError(f"megadl failed with exit code {code}")
    files = sorted(
        (os.path.join(dir_path, f) for f in os.listdir(dir_path) if os.path.isfile(os.path.join(dir_path, f))),
        key=os.path.getmtime,
    )
    if not files:
        raise RuntimeError("Mega download produced no files")
    path = files[-1]
    size = os.path.getsize(path)
    if name:
        renamed = os.path.join(dir_path, os.path.basename(name))
        if os.path.abspath(path) != os.path.abspath(renamed):
            os.replace(path, renamed)
            path = renamed
    return path, size
