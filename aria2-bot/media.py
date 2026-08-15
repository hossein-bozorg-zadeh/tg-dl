from __future__ import annotations

from pathlib import Path

from hachoir.metadata import extractMetadata
from hachoir.parser import createParser


def _metadata(path: Path):
    try:
        return extractMetadata(createParser(str(path)))
    except Exception:
        return None


def video_metadata(path: Path) -> tuple[int, int, int]:
    metadata = _metadata(path)
    width = height = duration = 0
    if metadata is not None:
        if metadata.has("duration"):
            duration = metadata.get("duration").seconds
        if metadata.has("width"):
            width = metadata.get("width")
        if metadata.has("height"):
            height = metadata.get("height")
    return width, height, duration


def audio_duration(path: Path) -> int:
    metadata = _metadata(path)
    if metadata is not None and metadata.has("duration"):
        return metadata.get("duration").seconds
    return 0
