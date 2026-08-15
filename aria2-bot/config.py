import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")

ARIA2_RPC_URL: str = os.getenv("ARIA2_RPC_URL", "http://127.0.0.1:6800/jsonrpc")
ARIA2_SECRET: str = os.getenv("ARIA2_SECRET", "aria2botsecret")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR: str = os.getenv("DOWNLOAD_DIR", os.path.join(BASE_DIR, "downloads"))

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
YTDLP_PROXIES: list[str] = [
    p.strip() for p in os.getenv("YTDLP_PROXIES", "").split(",") if p.strip()
]

# Optional cookies file for yt-dlp (e.g. a cookies.txt exported from your browser).
# Resolves YouTube "Sign in to confirm you're not a bot" issues.
YTDLP_COOKIES: str = os.getenv("YTDLP_COOKIES", "").strip()

# Cooldown between requests for non-authorized users (seconds)
COOLDOWN_SECONDS: int = int(os.getenv("COOLDOWN_SECONDS", "10"))

# Timeout for external tools (yt-dlp etc.)
PROCESS_MAX_TIMEOUT: int = int(os.getenv("PROCESS_MAX_TIMEOUT", "3700"))
