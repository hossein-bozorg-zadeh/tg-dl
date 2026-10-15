"""Best-effort SSRF guard for user-supplied download URLs.

Enforced by the bot only when access mode is "public" (i.e. any Telegram user
can submit links). The trusted private set — owner, granted users and
ALLOWED_USERS — is left unrestricted, matching the public/private toggle.

Note: this blocks obviously-local targets (loopback, RFC1918, link-local,
cloud metadata, reserved ranges). It cannot defeat DNS rebinding, because
aria2 resolves the host again when it actually connects; it is a guard rail,
not a hard boundary.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
from urllib.parse import urlparse

logger = logging.getLogger("aria2bot.netguard")

# Host-based fetches we police. magnet:/others are handed to aria2's BT engine
# and are not simple host fetches, so they are left alone.
ALLOWED_SCHEMES = {"http", "https", "ftp"}

BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "ip6-localhost",
    "ip6-loopback",
    "metadata",
    "metadata.google.internal",
    "metadata.google.internal.",
}


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _parse_ip(value: str):
    try:
        return ipaddress.ip_address(value.split("%")[0])
    except ValueError:
        return None


def _resolve(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, None)
    return [info[4][0] for info in infos]


async def is_safe_url(url: str) -> bool:
    """Return False if the URL targets a private/internal address."""
    parsed = urlparse(url)
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        return True

    host = parsed.hostname
    if not host:
        return False
    if host.lower() in BLOCKED_HOSTNAMES:
        logger.info("SSRF guard blocked hostname %s", host)
        return False

    literal = _parse_ip(host)
    if literal is not None:
        safe = not _is_blocked_ip(literal)
        if not safe:
            logger.info("SSRF guard blocked IP literal %s", host)
        return safe

    loop = asyncio.get_running_loop()
    try:
        addresses = await loop.run_in_executor(None, _resolve, host)
    except (socket.gaierror, OSError, UnicodeError):
        # If we can't resolve it, the download would fail anyway.
        return True

    for address in addresses:
        ip = _parse_ip(address)
        if ip is not None and _is_blocked_ip(ip):
            logger.info("SSRF guard blocked %s (resolves to %s)", host, address)
            return False
    return True
