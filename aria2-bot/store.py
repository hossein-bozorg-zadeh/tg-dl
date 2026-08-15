import json
import os
import secrets
import threading
import time
import uuid
from pathlib import Path

import config

LOCK = threading.Lock()
STORE_PATH = os.path.join(config.BASE_DIR, "requests.json")


def _load() -> dict:
    if not os.path.exists(STORE_PATH):
        return {"requests": {}, "thumbnails": {}, "last_seen": {}}
    with open(STORE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(data: dict) -> None:
    tmp = STORE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STORE_PATH)


def _cleanup_old_requests(data: dict) -> None:
    now = time.time()
    stale = [
        token for token, rec in data["requests"].items()
        if now - rec.get("created_at", 0) > 3600
    ]
    for token in stale:
        del data["requests"][token]
        work = data["requests"].get("_workdirs", {})
        data["requests"].setdefault("_workdirs", {}).pop(token, None)


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
        rec = data["requests"].get(token)
        return dict(rec) if rec else None


def delete_request(token: str) -> None:
    with LOCK:
        data = _load()
        data.setdefault("requests", {}).pop(token, None)
        data.setdefault("requests", {}).setdefault("_workdirs", {}).pop(token, None)
        _save(data)


def work_directory(token: str) -> Path:
    path = Path(config.DOWNLOAD_DIR) / f"req_{token}"
    path.mkdir(parents=True, exist_ok=True)
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
