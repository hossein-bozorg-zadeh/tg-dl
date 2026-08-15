from __future__ import annotations

import asyncio
import json
import logging
import random
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger("aria2bot.ytdlp")

VIDEO_EXTENSIONS = {"mp4", "mkv", "webm", "mov", "avi", "flv"}
AUDIO_EXTENSIONS = {"mp3", "m4a", "aac", "wav", "flac", "opus", "weba"}

MIB = 1024 * 1024


def humanbytes(size: int) -> str:
    size = float(size or 0)
    if size >= 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024 * 1024):.2f} GiB"
    if size >= MIB:
        return f"{size / MIB:.2f} MiB"
    if size >= 1024:
        return f"{size / 1024:.1f} KiB"
    return f"{size:.0f} B"


def _command_base(parsed_input, settings, use_cookies: bool = True) -> list[str]:
    command = ["yt-dlp", "--no-warnings"]
    proxies = getattr(settings, "YTDLP_PROXIES", None) or []
    if proxies:
        command.extend(["--proxy", random.choice(proxies)])
    elif getattr(settings, "HTTP_PROXY", ""):
        command.extend(["--proxy", settings.HTTP_PROXY])
    cookies = getattr(settings, "YTDLP_COOKIES", "")
    if use_cookies and cookies and Path(cookies).is_file():
        command.extend(["--cookies", cookies])
    if parsed_input.username:
        command.extend(["--username", parsed_input.username])
    if parsed_input.password:
        command.extend(["--password", parsed_input.password])
    return command


async def _run_command(command: list[str], cwd: Path | None = None) -> tuple[str, str]:
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(cwd) if cwd else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        error_text = stderr.decode().strip() or stdout.decode().strip() or "yt-dlp failed"
        raise RuntimeError(error_text)
    return stdout.decode().strip(), stderr.decode().strip()


async def _run_command_with_progress(command: list[str], cwd: Path | None, progress_cb=None) -> None:
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(cwd) if cwd else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    assert process.stdout is not None
    last_pct = -1
    error_lines: list[str] = []
    while True:
        line = await process.stdout.readline()
        if not line:
            break
        text = line.decode(errors="replace").strip()
        if not text:
            continue
        if text.startswith("ERROR"):
            error_lines.append(text)
        # Skip informational lines (they start with "[" or contain no percent).
        if text.startswith("[") or "%|" not in text:
            continue
        # yt-dlp --newline --progress-template output like: " 45.6%| 2.1MiB/s"
        try:
            pct_str = text.split("%")[0].strip()
            pct = float(pct_str)
            speed = text.split("|")[1].strip() if "|" in text else ""
            if pct - last_pct >= 0.5:
                last_pct = pct
                if progress_cb:
                    await progress_cb(pct, speed)
        except (ValueError, IndexError):
            continue
    code = await process.wait()
    if code != 0:
        detail = " | ".join(error_lines[-3:]) if error_lines else f"exit code {code}"
        raise RuntimeError(f"yt-dlp failed: {detail}")


def _is_audio_only(format_note: str | None) -> bool:
    return bool(format_note and "audio only" in format_note.lower())


def _label_for_format(format_data: dict, index: int) -> str:
    format_note = format_data.get("format_note") or format_data.get("format") or f"Format {index + 1}"
    size = format_data.get("filesize") or format_data.get("filesize_approx") or 0
    ext = format_data.get("ext", "")
    return f"Video {format_note} {ext} {humanbytes(size)}".strip()


def _ext_from_url(url: str) -> str | None:
    suffix = Path(urlparse(url).path).suffix
    return suffix.lstrip(".") if suffix else None


def _option_id(prefix: str, index: int) -> str:
    return f"{prefix}{index}"


async def probe_url(parsed_input, settings) -> dict:
    command = _command_base(parsed_input, settings, use_cookies=False)
    command.extend(["--dump-single-json", parsed_input.source_url])
    stdout, _ = await _run_command(command)
    if "\n" in stdout:
        stdout = stdout.splitlines()[0]
    return json.loads(stdout)


def build_quick_youtube_options() -> list[dict]:
    return [
        {"option_id": "quick_audio", "label": "🎵 Audio (MP3)", "send_type": "audio", "mode": "youtube_quick"},
        {"option_id": "quick_video", "label": "🎬 Video (MP4)", "send_type": "video", "mode": "youtube_quick"},
    ]


def build_youtube_quality_options(info: dict) -> list[dict]:
    """Build a quality/format selection menu for YouTube links."""
    options: list[dict] = []
    formats = info.get("formats") or []
    heights: dict[int, dict] = {}
    for f in formats:
        h = f.get("height")
        vcodec = f.get("vcodec")
        if not h or vcodec in (None, "none"):
            continue
        entry = heights.setdefault(h, {"height": h, "exts": set(), "size": 0})
        if f.get("ext"):
            entry["exts"].add(f["ext"])
        size = f.get("filesize") or f.get("filesize_approx") or 0
        entry["size"] = max(entry["size"], size)
    ordered = sorted(heights.values(), key=lambda e: e["height"], reverse=True)
    for idx, entry in enumerate(ordered[:12]):
        exts = sorted(entry["exts"], key=lambda e: 0 if e == "mp4" else (1 if e == "webm" else 2))
        ext_label = exts[0] if exts else "mp4"
        label = f"🎬 {entry['height']}p ({ext_label})"
        size = entry.get("size") or 0
        if size:
            label += f" {humanbytes(size)}"
        options.append(
            {
                "option_id": f"ytq{idx}",
                "label": label,
                "send_type": "video",
                "mode": "youtube_quality",
                "height": entry["height"],
                "file_ext": ext_label,
            }
        )
    if info.get("duration"):
        for quality in ("64k", "128k", "320k"):
            options.append(
                {
                    "option_id": f"yta{len(options)}",
                    "label": f"🎵 MP3 ({quality})",
                    "send_type": "audio",
                    "mode": "ytdlp_audio",
                    "file_ext": "mp3",
                    "audio_quality": quality,
                }
            )
    return options


def build_ytdlp_options(info: dict) -> list[dict]:
    options: list[dict] = []
    formats = info.get("formats") or []
    for index, format_data in enumerate(formats):
        format_note = format_data.get("format_note") or format_data.get("format")
        if format_note and "dash" in format_note.lower():
            continue
        if _is_audio_only(format_note):
            continue
        ext = format_data.get("ext")
        format_id = format_data.get("format_id")
        if not ext or not format_id:
            continue
        options.append(
            {
                "option_id": _option_id("fmt", len(options)),
                "label": _label_for_format(format_data, index),
                "send_type": "video",
                "mode": "ytdlp_format",
                "format_id": str(format_id),
                "file_ext": ext,
            }
        )
    if info.get("duration"):
        for quality in ("64k", "128k", "320k"):
            options.append(
                {
                    "option_id": _option_id("audio", len(options)),
                    "label": f"🎵 MP3 ({quality})",
                    "send_type": "audio",
                    "mode": "ytdlp_audio",
                    "file_ext": "mp3",
                    "audio_quality": quality,
                }
            )
    return options


def build_direct_options(parsed_input, info: dict | None = None) -> list[dict]:
    ext = None
    source_url = parsed_input.source_url
    if info:
        ext = info.get("ext")
    if not ext:
        ext = _ext_from_url(source_url)
    send_type = "document"
    if ext and ext.lower() in VIDEO_EXTENSIONS:
        send_type = "video"
    elif ext and ext.lower() in AUDIO_EXTENSIONS:
        send_type = "audio"
    options = [
        {
            "option_id": "direct_primary",
            "label": "Send as media" if send_type != "document" else "Send as document",
            "send_type": send_type,
            "mode": "direct",
            "file_ext": ext,
        }
    ]
    if send_type != "document":
        options.append(
            {
                "option_id": "direct_document",
                "label": "Send as document",
                "send_type": "document",
                "mode": "direct",
                "file_ext": ext,
            }
        )
    return options


def _pick_downloaded_file(work_dir: Path) -> Path:
    files = [
        path
        for path in work_dir.rglob("*")
        if path.is_file()
        and not path.name.endswith(".part")
        and path.suffix.lower() not in {".json", ".jpg", ".jpeg", ".png", ".webp"}
    ]
    if not files:
        raise RuntimeError("No file was downloaded")
    files.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    return files[0]


def _caption_from_info(info: dict, fallback: str) -> str:
    title = info.get("title")
    webpage = info.get("webpage_url")
    if title and webpage:
        return f'<b><a href="{webpage}">{title}</a></b>'
    return title or fallback


def _is_bot_detected(error: Exception) -> bool:
    text = str(error)
    return "Sign in to confirm" in text or "not a bot" in text.lower()


async def _download_with_retry(build_command, cwd: Path, progress_cb=None) -> None:
    """Run yt-dlp without cookies first; retry with cookies if bot-detection triggers."""
    try:
        await _run_command_with_progress(build_command(use_cookies=False), cwd=cwd, progress_cb=progress_cb)
    except RuntimeError as e:
        if not _is_bot_detected(e):
            raise
        logger.info("bot-detection without cookies, retrying with cookies: %s", e)
        await _run_command_with_progress(build_command(use_cookies=True), cwd=cwd, progress_cb=progress_cb)


async def download_quick_youtube(parsed_input, option: dict, settings, work_dir: Path, progress_cb=None) -> dict:
    info = await probe_url(parsed_input, settings)
    work_dir = work_dir.resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    args = ["--newline", "--progress-template", "%(progress._percent_str)s|%(progress._speed_str)s"]
    output_template = str(work_dir / "%(title)s [%(id)s].%(ext)s")
    if option.get("option_id") == "quick_audio":
        args.extend(
            ["-f", "bestaudio", "--extract-audio", "--audio-format", "mp3", "-o", output_template, parsed_input.source_url]
        )
        send_type = "audio"
    else:
        args.extend(["-f", "best[ext=mp4]/best", "-o", output_template, parsed_input.source_url])
        send_type = "video"
    await _download_with_retry(
        lambda use_cookies: _command_base(parsed_input, settings, use_cookies=use_cookies) + args,
        cwd=work_dir,
        progress_cb=progress_cb,
    )
    file_path = _pick_downloaded_file(work_dir)
    return {
        "path": file_path,
        "file_name": file_path.name,
        "send_type": send_type,
        "caption": _caption_from_info(info, file_path.stem),
    }


async def download_selected_format(parsed_input, option: dict, info: dict, settings, work_dir: Path, progress_cb=None) -> dict:
    work_dir = work_dir.resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    args = ["--newline", "--progress-template", "%(progress._percent_str)s|%(progress._speed_str)s"]
    output_template = str(work_dir / "%(title)s [%(id)s].%(ext)s")
    if option.get("mode") == "ytdlp_audio":
        args.extend(
            [
                "--extract-audio",
                "--audio-format",
                option.get("file_ext") or "mp3",
                "--audio-quality",
                option.get("audio_quality") or "128k",
                "-o",
                output_template,
                parsed_input.source_url,
            ]
        )
        send_type = "audio"
    elif option.get("mode") == "youtube_quality":
        height = int(option.get("height") or 1080)
        format_selector = f"bestvideo[height<={height}]+bestaudio/best[height<={height}]/best"
        args.extend(["-f", format_selector, "--merge-output-format", "mp4", "-o", output_template, parsed_input.source_url])
        send_type = "video"
    else:
        format_selector = option.get("format_id") or "best"
        if "youtube" in parsed_input.source_url or "youtu.be" in parsed_input.source_url:
            format_selector = f"{format_selector}+bestaudio"
        args.extend(["-f", format_selector, "--embed-subs", "-o", output_template, parsed_input.source_url])
        send_type = option.get("send_type", "video")
    await _download_with_retry(
        lambda use_cookies: _command_base(parsed_input, settings, use_cookies=use_cookies) + args,
        cwd=work_dir,
        progress_cb=progress_cb,
    )
    file_path = _pick_downloaded_file(work_dir)
    return {
        "path": file_path,
        "file_name": file_path.name,
        "send_type": send_type,
        "caption": _caption_from_info(info, file_path.stem),
    }
