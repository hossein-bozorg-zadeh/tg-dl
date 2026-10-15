import asyncio
from typing import Any

import aiohttp

import config

GIB = 1024 * 1024 * 1024
MIB = 1024 * 1024

# aria2 RPC calls should be quick; a stuck socket must not hang a handler.
RPC_TIMEOUT = aiohttp.ClientTimeout(total=30, sock_connect=10)


def _fmt_size(num: float) -> str:
    if num >= GIB:
        return f"{num / GIB:.2f} GiB"
    if num >= MIB:
        return f"{num / MIB:.2f} MiB"
    return f"{num / 1024:.1f} KiB"


def _fmt_speed(bps: float) -> str:
    return f"{_fmt_size(bps)}/s"


def _pct(down: str, total: str) -> str:
    try:
        total_f = float(total)
        down_f = float(down)
        if total_f <= 0:
            return "0%"
        return f"{down_f / total_f * 100:.1f}%"
    except (ValueError, ZeroDivisionError):
        return "0%"


STATUS_LABELS = {
    "active": "downloading",
    "waiting": "queued",
    "paused": "paused",
    "error": "error",
    "complete": "finished",
    "removed": "removed",
}


class Aria2Client:
    def __init__(self, url: str, secret: str, timeout: aiohttp.ClientTimeout = RPC_TIMEOUT):
        self.url = url
        self.secret = secret
        self.timeout = timeout
        self._rpc_id = 0
        self._session: aiohttp.ClientSession | None = None
        self._session_lock = asyncio.Lock()

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            async with self._session_lock:
                if self._session is None or self._session.closed:
                    self._session = aiohttp.ClientSession(timeout=self.timeout)
        return self._session

    async def close(self) -> None:
        session, self._session = self._session, None
        if session is not None and not session.closed:
            await session.close()

    async def call(self, method: str, *params) -> Any:
        self._rpc_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._rpc_id,
            "method": method,
            "params": [f"token:{self.secret}", *params],
        }
        session = await self._get_session()
        try:
            async with session.post(self.url, json=payload) as resp:
                data = await resp.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise RuntimeError(f"aria2 RPC unreachable: {exc}") from exc
        if not isinstance(data, dict):
            raise RuntimeError(f"aria2 RPC returned an unexpected payload: {data!r}")
        if "error" in data:
            error = data["error"]
            message = error.get("message", str(error)) if isinstance(error, dict) else str(error)
            raise RuntimeError(message)
        return data.get("result")

    async def add_uri(self, uris: list[str], options: dict | None = None) -> str:
        opts = {"dir": config.DOWNLOAD_DIR}
        if options:
            opts.update(options)
        return await self.call("aria2.addUri", uris, opts)

    async def add_torrent(self, base64: str, options: dict | None = None) -> str:
        opts = {"dir": config.DOWNLOAD_DIR}
        if options:
            opts.update(options)
        return await self.call("aria2.addTorrent", base64, [], opts)

    async def get_status(self, gid: str) -> dict:
        return await self.call("aria2.tellStatus", gid, ["gid", "status", "totalLength", "completedLength", "downloadSpeed", "bittorrent", "files", "errorMessage"])

    async def tell_active(self) -> list[dict]:
        return await self.call("aria2.tellActive")

    async def tell_waiting(self) -> list[dict]:
        return await self.call("aria2.tellWaiting", 0, 100)

    async def tell_stopped(self) -> list[dict]:
        return await self.call("aria2.tellStopped", 0, 100)

    async def all_status(self) -> list[dict]:
        items = await self.tell_active() + await self.tell_waiting()
        for g in items:
            g["_stopped"] = False
        stopped = await self.tell_stopped()
        for g in stopped:
            g["_stopped"] = True
        items.extend(stopped)
        return items

    async def pause(self, gid: str) -> str:
        return await self.call("aria2.pause", gid)

    async def unpause(self, gid: str) -> str:
        return await self.call("aria2.unpause", gid)

    async def remove(self, gid: str) -> str:
        return await self.call("aria2.remove", gid)

    async def remove_result(self, gid: str) -> str:
        return await self.call("aria2.removeDownloadResult", gid)

    @staticmethod
    def format_status(status: dict) -> str:
        gid = status.get("gid", "?")
        raw = status.get("status", "unknown")
        label = STATUS_LABELS.get(raw, raw)

        name = "unknown"
        files = status.get("files") or []
        if files:
            name = files[0].get("path", "unknown").split("/")[-1]
        bt = status.get("bittorrent")
        if bt and bt.get("info") and bt["info"].get("name"):
            name = bt["info"]["name"]

        total = int(status.get("totalLength") or 0)
        done = int(status.get("completedLength") or 0)
        speed = int(status.get("downloadSpeed") or 0)

        line = f"📦 {name}\n"
        line += f"🆔 `{gid}`\n"
        line += f"📊 {_pct(done, total)} ({_fmt_size(done)} / {_fmt_size(total)})\n"
        line += f"⚡ {_fmt_speed(speed)}\n"
        line += f"🔁 {label}"
        if raw == "error":
            line += f"\n❌ {status.get('errorMessage', 'unknown error')}"
        return line
