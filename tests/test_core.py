"""Regression tests for the review fixes.

Run directly:  python tests/test_core.py
Or with pytest: pytest -q
"""

import asyncio
import glob
import json
import os
import sys
import time

import env  # noqa: F401  (bootstrap: sys.path + isolated config)

import config  # noqa: E402
import db  # noqa: E402
import netguard  # noqa: E402
import store  # noqa: E402
import ytdlp  # noqa: E402


class Parsed:
    source_url = "http://example.com/file.bin"
    custom_file_name = None
    username = None
    password = None


# --------------------------------------------------------------------------
# db / store persistence
# --------------------------------------------------------------------------

def test_missing_files_key_does_not_crash():
    with open(db.DB_PATH, "w", encoding="utf-8") as fh:
        json.dump({"admins": [7], "users": {}, "history": {}, "settings": {}}, fh)
    assert db.find_file("http://missing/") is None
    assert db.touch_file("http://missing/")["requests"] == 1


def test_corrupt_data_is_quarantined():
    before = len(glob.glob(os.path.join(env.TEST_TMP, "bot_data.json.corrupt-*")))
    with open(db.DB_PATH, "w", encoding="utf-8") as fh:
        fh.write("{ not valid json")
    db.get_admins()
    after = len(glob.glob(os.path.join(env.TEST_TMP, "bot_data.json.corrupt-*")))
    assert after == before + 1


def test_non_dict_json_falls_back_to_defaults():
    with open(db.DB_PATH, "w", encoding="utf-8") as fh:
        fh.write("[1, 2, 3]")
    assert db.get_admins() == []


def test_cache_is_scoped_per_user():
    db.touch_file("http://scoped/", 111)
    assert db.find_file("http://scoped/", 111) is not None
    assert db.find_file("http://scoped/", 222) is None


def test_prune_files_drops_expired_entries():
    db.touch_file("http://fresh/", 43)
    db.touch_file("http://old/", 42)
    data = db._load()
    for rec in data["files"].values():
        if isinstance(rec, dict) and rec.get("url") == "http://old/":
            rec["last_request"] = time.time() - 10 * 86400
    db._save(data)
    assert db.prune_files(7) >= 1
    assert db.find_file("http://old/", 42) is None
    assert db.find_file("http://fresh/", 43) is not None


def test_request_cleanup_removes_expired_workdir():
    token = store.create_request("direct_download", Parsed(), [{"option_id": "o", "label": "L"}])
    work = store.work_directory(token)
    assert work.is_dir()

    data = store._load()
    data["requests"][token]["created_at"] = time.time() - 7200
    store._save(data)

    fresh = store.create_request("direct_download", Parsed(), [{"option_id": "o", "label": "L"}])
    data = store._load()
    assert token not in data["requests"]
    assert fresh in data["requests"]
    assert not work.exists()
    assert "_workdirs" not in data["requests"]


def test_delete_request_removes_workdir():
    token = store.create_request("direct_download", Parsed(), [{"option_id": "o", "label": "L"}])
    work = store.work_directory(token)
    store.delete_request(token)
    assert store.load_request(token) is None
    assert not work.exists()


def test_concurrency_guard():
    assert store.acquire_download(5, 2) is True
    assert store.acquire_download(5, 2) is True
    assert store.acquire_download(5, 2) is False
    store.release_download(5)
    assert store.acquire_download(5, 2) is True
    assert store.acquire_download(6, 0) is True


# --------------------------------------------------------------------------
# yt-dlp helpers
# --------------------------------------------------------------------------

def test_caption_escaping():
    cap = ytdlp._caption_from_info(
        {"title": "<b>x</b>&y", "webpage_url": "http://a/?b=1&c=2"}, "fb"
    )
    assert "&lt;b&gt;x&lt;/b&gt;&amp;y" in cap
    assert "b=1&amp;c=2" in cap
    assert "<b>x</b>" not in cap


def test_probe_json_parsing():
    assert ytdlp._parse_probe_json('{"a": 1}') == {"a": 1}
    assert ytdlp._parse_probe_json('[debug] hi\n{"a": 2}') == {"a": 2}


def test_run_command_times_out():
    original = config.PROCESS_MAX_TIMEOUT
    config.PROCESS_MAX_TIMEOUT = 1
    try:
        try:
            asyncio.run(ytdlp._run_command([sys.executable, "-c", "import time; time.sleep(30)"]))
        except RuntimeError as exc:
            assert "timed out" in str(exc)
        else:
            raise AssertionError("expected a timeout")
    finally:
        config.PROCESS_MAX_TIMEOUT = original


# --------------------------------------------------------------------------
# SSRF guard
# --------------------------------------------------------------------------

def test_netguard_blocks_internal_targets():
    blocked = [
        "http://127.0.0.1/x",
        "http://localhost/x",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/x",
        "http://192.168.1.1/",
        "http://[::1]/x",
        "http://0.0.0.0/",
    ]
    for url in blocked:
        assert asyncio.run(netguard.is_safe_url(url)) is False, url


def test_netguard_allows_public_and_magnet():
    assert asyncio.run(netguard.is_safe_url("https://example.com/")) is True
    assert asyncio.run(netguard.is_safe_url("magnet:?xt=urn:btih:abc")) is True


if __name__ == "__main__":
    import traceback

    failed = 0
    tests = [
        (name, fn)
        for name, fn in sorted(globals().items())
        if name.startswith("test_") and callable(fn)
    ]
    for name, fn in tests:
        try:
            fn()
            print(f"[PASS] {name}")
        except Exception:
            failed += 1
            print(f"[FAIL] {name}")
            traceback.print_exc()
    print()
    if failed:
        print(f"{failed} FAILURE(S)")
        raise SystemExit(1)
    print("ALL TESTS PASSED")
