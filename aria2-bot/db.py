import hashlib
import json
import os
import threading
import time

import config

DB_PATH = os.path.join(config.BASE_DIR, "bot_data.json")
LOCK = threading.Lock()


def _load() -> dict:
    if not os.path.exists(DB_PATH):
        return {"admins": [], "files": {}}
    with open(DB_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(data: dict) -> None:
    tmp = DB_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DB_PATH)


def get_admins() -> list[int]:
    with LOCK:
        data = _load()
        return list(data.get("admins", []))


def add_admin(user_id: int) -> None:
    with LOCK:
        data = _load()
        admins = data.setdefault("admins", [])
        if user_id not in admins:
            admins.append(user_id)
        _save(data)


def remove_admin(user_id: int) -> None:
    with LOCK:
        data = _load()
        admins = data.get("admins", [])
        if user_id in admins:
            admins.remove(user_id)
        _save(data)


def is_allowed(user_id: int) -> bool:
    if user_id == config.OWNER_ID:
        return True
    return user_id in get_admins() or user_id in config.ALLOWED_USERS


# ---- File cache / dedupe index -------------------------------------------
# key: canonical URL hash -> record
# record: {
#   "url": original url,
#   "name": file name,
#   "size": total bytes,
#   "last_request": unix ts,
#   "requests": count,
#   "parts": [{ "name": ..., "msg_id": channel message id }],
#   "channel_chat_id": channel id where parts live
# }


def _url_key(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]


def find_file(url: str) -> dict | None:
    with LOCK:
        data = _load()
        rec = data["files"].get(_url_key(url))
        if not rec:
            return None
        rec = dict(rec)
    return rec


def touch_file(url: str) -> dict:
    key = _url_key(url)
    with LOCK:
        data = _load()
        rec = data["files"].setdefault(
            key,
            {"url": url, "name": "", "size": 0, "last_request": 0, "requests": 0, "parts": [], "channel_chat_id": config.CHANNEL_ID},
        )
        rec["last_request"] = int(time.time())
        rec["requests"] = rec.get("requests", 0) + 1
        _save(data)
        return dict(rec)


def set_file_parts(url: str, name: str, size: int, parts: list[dict]) -> dict:
    key = _url_key(url)
    with LOCK:
        data = _load()
        rec = data["files"].setdefault(key, {"url": url, "last_request": int(time.time()), "requests": 0, "parts": [], "channel_chat_id": config.CHANNEL_ID})
        rec["name"] = name
        rec["size"] = size
        rec["parts"] = parts
        rec["channel_chat_id"] = config.CHANNEL_ID
        _save(data)
        return dict(rec)
