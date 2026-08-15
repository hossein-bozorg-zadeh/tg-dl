from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse


@dataclass(slots=True)
class ParsedInput:
    source_url: str
    custom_file_name: str | None = None
    username: str | None = None
    password: str | None = None
    extra_urls: list[str] = field(default_factory=list)


def extract_link_text(text: str) -> str | None:
    if "http://" in text or "https://" in text or "magnet:?" in text:
        return text
    return None


def parse_user_input(text: str) -> ParsedInput:
    # url|filename
    # url|filename|username|password
    if "|" in text:
        parts = [part.strip() for part in text.split("|")]
        if len(parts) == 2:
            return ParsedInput(source_url=parts[0], custom_file_name=parts[1])
        if len(parts) == 4:
            return ParsedInput(
                source_url=parts[0],
                custom_file_name=parts[1],
                username=parts[2],
                password=parts[3],
            )
        if len(parts) > 4:
            url = parts[0]
            name = parts[1]
            auth = parts[2:]
            return ParsedInput(
                source_url=url,
                custom_file_name=name,
                username=auth[0] if auth else None,
                password=auth[1] if len(auth) > 1 else None,
                extra_urls=[p for p in parts[2:] if p.startswith(("http", "magnet:"))],
            )

    if " * " in text:
        url, file_name = [part.strip() for part in text.split(" * ", maxsplit=1)]
        return ParsedInput(source_url=url, custom_file_name=file_name)

    return ParsedInput(source_url=text.strip())


def is_probable_youtube_url(url: str) -> bool:
    hostname = (urlparse(url).hostname or "").lower()
    return (
        hostname == "youtube.com"
        or hostname.endswith(".youtube.com")
        or hostname == "youtu.be"
        or hostname.endswith(".youtu.be")
    )


def is_direct_file_url(url: str) -> bool:
    if is_probable_youtube_url(url):
        return False
    path = urlparse(url).path
    if not path:
        return False
    suffix = path.rsplit("/", 1)[-1].lower()
    if "." not in suffix:
        return False
    return True
