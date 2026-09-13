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
        return {"admins": [], "files": {}, "users": {}, "history": {}, "settings": {}}
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
    if user_id in get_banned():
        return False
    if get_access_mode() == "public":
        return True
    return user_id in get_admins() or user_id in config.ALLOWED_USERS


def get_banned() -> list[int]:
    with LOCK:
        return list(_load().get("settings", {}).get("banned", []))


def ban_user(user_id: int) -> None:
    with LOCK:
        data = _load()
        banned = data.setdefault("settings", {}).setdefault("banned", [])
        if user_id not in banned:
            banned.append(user_id)
        _save(data)


def unban_user(user_id: int) -> None:
    with LOCK:
        data = _load()
        banned = data.setdefault("settings", {}).setdefault("banned", [])
        if user_id in banned:
            banned.remove(user_id)
        _save(data)


def is_known_user(user_id: int) -> bool:
    with LOCK:
        return str(user_id) in _load().get("users", {})


def get_access_mode() -> str:
    with LOCK:
        return _load().get("settings", {}).get("access_mode", "private")


def set_access_mode(mode: str) -> None:
    if mode not in {"public", "private"}:
        raise ValueError("access mode must be public or private")
    with LOCK:
        data = _load()
        data.setdefault("settings", {})["access_mode"] = mode
        _save(data)


def record_user(user_id: int, first_name: str = "", username: str = "") -> None:
    with LOCK:
        data = _load()
        data.setdefault("users", {})[str(user_id)] = {
            "id": user_id,
            "first_name": first_name or "",
            "username": username or "",
            "updated_at": int(time.time()),
        }
        _save(data)


def get_user(user_id: int) -> dict:
    with LOCK:
        return dict(_load().get("users", {}).get(str(user_id), {"id": user_id}))


def add_history(user_id: int, url: str, name: str, size: int, status: str = "completed") -> None:
    with LOCK:
        data = _load()
        entries = data.setdefault("history", {}).setdefault(str(user_id), [])
        entries.insert(0, {
            "url": url,
            "name": name,
            "size": size,
            "status": status,
            "timestamp": int(time.time()),
        })
        del entries[50:]
        _save(data)


def get_history(user_id: int, limit: int = 50) -> list[dict]:
    with LOCK:
        return list(_load().get("history", {}).get(str(user_id), [])[:limit])


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
