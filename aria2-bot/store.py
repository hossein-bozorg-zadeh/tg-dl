import json
import logging
import os
import secrets
import shutil
import threading
import time
from pathlib import Path

import config

logger = logging.getLogger("aria2bot.store")

LOCK = threading.Lock()
STORE_PATH = os.path.join(config.BASE_DIR, "requests.json")
REQUEST_TTL_SECONDS = 3600


def _default_data() -> dict:
    return {"requests": {}, "workdirs": {}, "thumbnails": {}, "last_seen": {}}


def _quarantine(path: str) -> None:
    """Move an unreadable data file aside so the bot can keep running."""
    try:
        broken = f"{path}.corrupt-{int(time.time())}"
        os.replace(path, broken)
        logger.error("Moved unreadable data file to %s", broken)
    except OSError:
        logger.exception("Could not quarantine unreadable data file %s", path)


def _load() -> dict:
    if not os.path.exists(STORE_PATH):
        return _default_data()
    try:
        with open(STORE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        logger.exception("requests.json is unreadable; starting from defaults")
        _quarantine(STORE_PATH)
        return _default_data()
    if not isinstance(data, dict):
        logger.error("requests.json has unexpected type %s; starting from defaults", type(data).__name__)
        _quarantine(STORE_PATH)
        return _default_data()
    for key, value in _default_data().items():
        data.setdefault(key, value)
    if not isinstance(data.get("requests"), dict):
        data["requests"] = {}
    if not isinstance(data.get("workdirs"), dict):
        data["workdirs"] = {}
    return data


def _save(data: dict) -> None:
    tmp = STORE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, STORE_PATH)


def _cleanup_old_requests(data: dict) -> None:
    """Drop expired format-selection requests and their temp directories.

    Work directories live in their own top-level key (never inside
    "requests"), so they cannot be mistaken for request records.
    """
    now = time.time()
    requests = data.setdefault("requests", {})
    workdirs = data.setdefault("workdirs", {})
    stale = [
        token
        for token, rec in requests.items()
        if isinstance(rec, dict) and now - rec.get("created_at", now) > REQUEST_TTL_SECONDS
    ]
    for token in stale:
        requests.pop(token, None)
        path = workdirs.pop(token, None)
        if path:
            shutil.rmtree(path, ignore_errors=True)


# --- Request store (format selection flow) -------------------------------

def create_request(request_type: str, parsed, options: list[dict], info: dict | None = None) -> str:
    token = secrets.token_hex(6)
    with LOCK:
        data = _load()
        data.setdefault("requests", {})
        data["requests"][token] = {
            "token": token,
            "request_type": request_type,
            "parsed": {
                "source_url": parsed.source_url,
                "custom_file_name": parsed.custom_file_name,
                "username": parsed.username,
                "password": parsed.password,
            },
            "options": options,
            "info": info or {},
            "created_at": time.time(),
        }
        _cleanup_old_requests(data)
        _save(data)
    return token


def load_request(token: str) -> dict | None:
    with LOCK:
        data = _load()
        rec = data.get("requests", {}).get(token)
        return dict(rec) if rec else None


def delete_request(token: str) -> None:
    with LOCK:
        data = _load()
        data.setdefault("requests", {}).pop(token, None)
        path = data.setdefault("workdirs", {}).pop(token, None)
        _save(data)
    if path:
        shutil.rmtree(path, ignore_errors=True)


def work_directory(token: str) -> Path:
    path = Path(config.DOWNLOAD_DIR) / f"req_{token}"
    path.mkdir(parents=True, exist_ok=True)
    with LOCK:
        data = _load()
        data.setdefault("workdirs", {})[token] = str(path)
        _save(data)
    return path


# --- Thumbnails -----------------------------------------------------------

def thumbnail_path(user_id: int) -> Path:
    d = Path(config.DOWNLOAD_DIR) / "thumbnails"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{user_id}.jpg"


def save_thumbnail(user_id: int, data: bytes) -> Path:
    path = thumbnail_path(user_id)
    path.write_bytes(data)
    return path


def get_thumbnail(user_id: int) -> str | None:
    path = thumbnail_path(user_id)
    return str(path) if path.exists() else None


def delete_thumbnail(user_id: int) -> bool:
    path = thumbnail_path(user_id)
    if path.exists():
        path.unlink(missing_ok=True)
        return True
    return False


# --- Cooldown -------------------------------------------------------------

def cooldown_check(user_id: int, timeout_seconds: int = 10) -> int:
    if user_id in config.ALLOWED_USERS or user_id == config.OWNER_ID or user_id in db_admins():
        return 0
    with LOCK:
        data = _load()
        last = data.setdefault("last_seen", {}).get(str(user_id), 0)
        now = time.time()
        data["last_seen"][str(user_id)] = now
        _save(data)
    if last == 0:
        return 0
    elapsed = now - last
    if elapsed >= timeout_seconds:
        return 0
    return int(timeout_seconds - elapsed)


def db_admins() -> list[int]:
    import db
    return db.get_admins()
