import json
import os
import re

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")

ARIA2_RPC_URL: str = os.getenv("ARIA2_RPC_URL", "http://127.0.0.1:6800/jsonrpc")
ARIA2_SECRET: str = os.getenv("ARIA2_SECRET", "aria2botsecret")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR: str = os.getenv("DOWNLOAD_DIR", os.path.join(BASE_DIR, "downloads"))

# proxies.json uploaded to the bot (owner-only) takes priority over YTDLP_PROXIES env.
PROXIES_JSON: str = os.getenv("PROXIES_JSON", os.path.join(BASE_DIR, "proxies.json"))


def _normalize_proxy_string(value: str) -> str:
    """Coerce a raw proxy string into a yt-dlp-friendly URL."""
    value = (value or "").strip()
    if not value:
        return ""
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", value):
        return value
    # "user:pass@ip:port" -> http://user:pass@ip:port
    # "ip:port" -> http://ip:port
    return f"http://{value}"


def _coerce_string_item(value: str):
    """If a string is actually a JSON object/array, parse it back."""
    stripped = value.strip()
    if stripped.startswith(("{", "[")):
        try:
            return json.loads(stripped)
        except ValueError:
            pass
    return value


def _proxy_from_dict(item: dict) -> str:
    """Extract a proxy URL from a dict, covering common JSON formats."""
    url = item.get("url") or item.get("proxy") or item.get("proxy_url") or item.get("address")
    if isinstance(url, str) and url.strip():
        return _normalize_proxy_string(url)
    host = item.get("ip") or item.get("host") or item.get("hostname") or item.get("server") or item.get("addr")
    port = item.get("port")
    if not host or port is None:
        return ""
    protocols = item.get("protocols") or item.get("protocol") or item.get("scheme") or item.get("type")
    if isinstance(protocols, (list, tuple)):
        protocol = str(protocols[0] if protocols else "http").lower()
    else:
        protocol = str(protocols or "http").lower()
    auth = ""
    user = item.get("username") or item.get("user") or item.get("login") or item.get("auth_user")
    password = item.get("password") or item.get("pass") or item.get("pwd") or item.get("auth_pass")
    if user:
        auth = f"{user}:{password or ''}@"
    return f"{protocol}://{auth}{host}:{port}"


def extract_proxy_list(raw) -> list[str]:
    """Parse a proxies JSON document into a list of proxy URLs.
    Accepts arrays, objects, or nested containers with many field names."""
    proxies: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            for key in ("proxies", "proxy", "proxy_list", "items", "data", "list", "result", "servers"):
                child = node.get(key)
                if child is not None:
                    walk(child)
            if not any(k in node for k in ("proxies", "proxy", "proxy_list", "items", "data", "list", "result", "servers")):
                url = _proxy_from_dict(node)
                if url:
                    proxies.append(url)
        elif isinstance(node, list):
            for child in node:
                walk(child)
        elif isinstance(node, str):
            coerced = _coerce_string_item(node)
            if isinstance(coerced, dict):
                url = _proxy_from_dict(coerced)
                if url:
                    proxies.append(url)
            elif isinstance(coerced, list):
                walk(coerced)
            else:
                url = _normalize_proxy_string(node)
                if url:
                    proxies.append(url)

    walk(raw)
    seen: set[str] = set()
    unique: list[str] = []
    for p in proxies:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique


def extract_proxies_from_text(text: str) -> list[str]:
    """Best-effort parse of arbitrary proxy file text (non-JSON).
    Tries to find JSON objects inline, then falls back to line splitting."""
    parsed: list[str] = []
    seen: set[str] = set()

    def add(normalized: str):
        if normalized and normalized not in seen:
            seen.add(normalized)
            parsed.append(normalized)

    # 1) Try whole-text JSON (could be wrapped, multi-line, with BOM).
    cleaned = text.lstrip("\ufeff").strip()
    try:
        return extract_proxy_list(json.loads(cleaned))
    except (ValueError, TypeError):
        pass

    # 2) Find inline {...} objects (JSON objects embedded in text or broken JSON).
    for match in re.finditer(r"\{[^{}]*\}", cleaned, flags=re.DOTALL):
        try:
            obj_text = match.group(0)
            obj_text = re.sub(r",\s*([}\]])", r"\1", obj_text)  # drop trailing commas
            obj = json.loads(obj_text)
            add(_proxy_from_dict(obj))
        except (ValueError, TypeError):
            continue
    if parsed:
        return parsed

    # 3) Line / comma / semicolon splitting.
    for line in re.split(r"[\n;,]+", cleaned):
        item = line.strip()
        if not item or item.startswith(("#", "//", "/*")):
            continue
        for token in re.split(r"\s+", item):
            token = token.strip()
            if not token or token.startswith(("#", "//")):
                continue
            if ":" not in token:
                continue
            if token.lower() in {"ip:port", "host:port", "proxy:port", "address:port", "addr:port"}:
                continue
            add(_normalize_proxy_string(token))
    return parsed


def load_proxies() -> list[str]:
    proxies: list[str] = [
        p.strip() for p in os.getenv("YTDLP_PROXIES", "").split(",") if p.strip()
    ]
    try:
        with open(PROXIES_JSON, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        proxies.extend(extract_proxy_list(raw))
    except (OSError, ValueError):
        pass
    seen: set[str] = set()
    unique: list[str] = []
    for p in proxies:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique

# Owner: can manage admins, always allowed.
OWNER_ID: int = int(os.getenv("OWNER_ID", "0") or 0)

# Private channel used to store uploaded files + download log.
# Must be a numeric channel/supergroup id (get it from @userinfobot or bot logs).
CHANNEL_ID: int = int(os.getenv("CHANNEL_ID", "0") or 0)

# Extra allowed user ids (besides owner). Managed at runtime via the admin panel.
ALLOWED_USERS: list[int] = [
    int(x) for x in os.getenv("ALLOWED_USERS", "").split(",") if x.strip()
]

# Split threshold and part size for large files.
SPLIT_THRESHOLD: int = int(os.getenv("SPLIT_THRESHOLD", "2147483648"))  # 2 GiB
SPLIT_PART_SIZE: int = int(os.getenv("SPLIT_PART_SIZE", "1610612736"))  # 1.5 GiB

# Files requested again within this window are re-sent from the channel cache.
CACHE_TTL_DAYS: int = int(os.getenv("CACHE_TTL_DAYS", "7"))

# MTProto credentials for large file uploads.
TELEGRAM_API_ID: int = int(os.getenv("TELEGRAM_API_ID", "0") or 0)
TELEGRAM_API_HASH: str = os.getenv("TELEGRAM_API_HASH", "")

MAX_BOTAPI_SIZE: int = 49 * 1024 * 1024  # 49 MiB
MAX_MT_PROTO_SIZE: int = 2 * 1024 * 1024 * 1024  # 2 GiB

# Direct-download chunk size (bytes). Values <1024 treated as KiB for back-compat.
CHUNK_SIZE: int = (lambda v: v * 1024 if v < 1024 else v)(int(os.getenv("CHUNK_SIZE", "128") or 128))

# Proxy for network requests + yt-dlp (optional)
HTTP_PROXY: str = os.getenv("HTTP_PROXY", "").strip()

# Comma-separated proxy list used by yt-dlp (rotated per request).
# Helps avoid YouTube bot-detection / login prompts. Empty = no proxy.
# Example: "socks5://127.0.0.1:9050,http://user:pass@host:port"
# A proxies.json file uploaded to the bot overrides these.
YTDLP_PROXIES: list[str] = load_proxies()

# Optional cookies file for yt-dlp (e.g. a cookies.txt exported from your browser).
# Resolves YouTube "Sign in to confirm you're not a bot" issues.
YTDLP_COOKIES: str = os.getenv("YTDLP_COOKIES", "").strip()

# Cooldown between requests for non-authorized users (seconds)
COOLDOWN_SECONDS: int = int(os.getenv("COOLDOWN_SECONDS", "10"))

# Timeout for external tools (yt-dlp etc.)
PROCESS_MAX_TIMEOUT: int = int(os.getenv("PROCESS_MAX_TIMEOUT", "3700"))
