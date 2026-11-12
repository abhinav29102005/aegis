"""Outbound webhook URL validation and SSRF protection."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

_CGNAT_NETWORK = ipaddress.IPv4Network("100.64.0.0/10")
_UNSPECIFIED_V4_NETWORK = ipaddress.IPv4Network("0.0.0.0/8")

_BLOCKED_HOSTNAMES = frozenset({
    "localhost",
    "localhost.localdomain",
    "ip6-localhost",
    "ip6-loopback",
    "metadata.google.internal",
    "metadata",
})

_BLOCKED_SUFFIXES = (
    ".localhost",
    ".local",
    ".internal",
    ".localdomain",
)


class SSRFValidationError(ValueError):
    """Raised when a URL violates outbound SSRF / network boundary controls."""


def _unwrap_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


def is_public_ip(ip_str: str) -> bool:
    """Return True iff ``ip_str`` is a globally routable public IPv4/IPv6 address."""
    try:
        parsed = ipaddress.ip_address(ip_str.strip())
    except ValueError:
        return False

    ip = _unwrap_ip(parsed)
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or not ip.is_global
    ):
        return False

    return not (
        isinstance(ip, ipaddress.IPv4Address)
        and (ip in _CGNAT_NETWORK or ip in _UNSPECIFIED_V4_NETWORK)
    )


def _try_parse_ip_literal(hostname: str) -> str | None:
    try:
        ip = ipaddress.ip_address(hostname)
        return str(_unwrap_ip(ip))
    except ValueError:
        pass
    # Catch non-standard integer/hex/octal/short IPv4 literals (e.g. 127.1, 0x7f000001, 2130706433)
    if hostname.isdigit() or hostname.lower().startswith("0x"):
        try:
            packed = socket.inet_aton(hostname)
            return socket.inet_ntoa(packed)
        except OSError:
            return None
    parts = hostname.split(".")
    if 2 <= len(parts) <= 4 and all(p.isdigit() or p.lower().startswith("0x") for p in parts):
        try:
            packed = socket.inet_aton(hostname)
            return socket.inet_ntoa(packed)
        except OSError:
            return None
    return None


def validate_webhook_url(
    url: str,
    *,
    require_https: bool = False,
    resolve_dns: bool = True,
) -> list[str]:
    """Validate an outbound webhook URL against SSRF and return resolved public IPs."""
    if not isinstance(url, str) or not url:
        raise SSRFValidationError("Webhook URL must be a non-empty string")
    if url != url.strip() or any(ord(ch) < 32 or ord(ch) == 127 for ch in url):
        raise SSRFValidationError("Webhook URL contains invalid whitespace or control characters")

    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if require_https:
        if scheme != "https":
            raise SSRFValidationError("Webhook URL must use HTTPS")
    elif scheme not in {"http", "https"}:
        raise SSRFValidationError("Webhook URL scheme must be http or https")

    if parsed.username is not None or parsed.password is not None:
        raise SSRFValidationError("Webhook URL must not embed userinfo credentials")

    try:
        port = parsed.port
    except ValueError as exc:
        raise SSRFValidationError("Webhook URL contains an invalid port") from exc
    if port is not None and not (1 <= port <= 65535):
        raise SSRFValidationError("Webhook URL port out of range")

    raw_host = parsed.hostname
    if not raw_host:
        raise SSRFValidationError("Webhook URL must contain a valid hostname")

    hostname = raw_host.strip().rstrip(".").lower()
    if not hostname:
        raise SSRFValidationError("Webhook URL must contain a valid hostname")

    if hostname in _BLOCKED_HOSTNAMES or any(hostname.endswith(suffix) for suffix in _BLOCKED_SUFFIXES):
        raise SSRFValidationError(f"Webhook hostname '{hostname}' is blocked")

    ip_literal = _try_parse_ip_literal(hostname)
    if ip_literal is not None:
        if not is_public_ip(ip_literal):
            raise SSRFValidationError(f"Webhook IP '{ip_literal}' is not a public routable address")
        return [ip_literal]

    if not resolve_dns:
        return []

    target_port = port or (443 if scheme == "https" else 80)
    try:
        addr_info = socket.getaddrinfo(hostname, target_port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise SSRFValidationError(f"Unable to resolve webhook hostname '{hostname}'") from exc

    resolved_ips: list[str] = []
    seen: set[str] = set()
    for entry in addr_info:
        sockaddr = entry[4]
        if not sockaddr:
            continue
        raw_ip = str(sockaddr[0]).split("%", 1)[0]
        if not is_public_ip(raw_ip):
            raise SSRFValidationError(
                f"Webhook hostname '{hostname}' resolved to non-public address '{raw_ip}'"
            )
        normalized = str(_unwrap_ip(ipaddress.ip_address(raw_ip)))
        if normalized not in seen:
            seen.add(normalized)
            resolved_ips.append(normalized)

    if not resolved_ips:
        raise SSRFValidationError(f"Webhook hostname '{hostname}' resolved to no addresses")

    return resolved_ips
