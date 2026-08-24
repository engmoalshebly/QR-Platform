"""Small, dependency-free security helpers shared by request handlers."""
from __future__ import annotations

import hashlib
import hmac
from functools import lru_cache
from ipaddress import ip_address, ip_network

from starlette.requests import Request

from app.config import get_settings

settings = get_settings()


@lru_cache(maxsize=1)
def _trusted_proxy_networks() -> tuple:
    networks = []
    for value in settings.trusted_proxy_ips.split(","):
        value = value.strip()
        if not value:
            continue
        try:
            networks.append(ip_network(value, strict=False))
        except ValueError:
            continue
    return tuple(networks)


def _is_trusted_proxy(value: str | None) -> bool:
    if not value:
        return False
    try:
        address = ip_address(value)
    except ValueError:
        return False
    return any(address in network for network in _trusted_proxy_networks())


def get_client_ip(request: Request) -> str | None:
    """Return a forwarded client IP only when the immediate peer is trusted."""
    peer_ip = request.client.host if request.client else None
    if not _is_trusted_proxy(peer_ip):
        return peer_ip

    forwarded_chain: list[str] = []
    for candidate in request.headers.get("x-forwarded-for", "").split(","):
        try:
            forwarded_chain.append(str(ip_address(candidate.strip())))
        except ValueError:
            continue

    for candidate in reversed([*forwarded_chain, peer_ip]):
        if candidate and not _is_trusted_proxy(candidate):
            return candidate
    return peer_ip


def request_path_template(request: Request) -> str:
    """Return a route template, never a token-bearing raw URL path."""
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else "unmatched"


def hmac_digest(value: str, *, purpose: str) -> str:
    """Derive a non-reversible, purpose-bound digest for short-lived secrets."""
    payload = f"{purpose}:{value}".encode("utf-8")
    return hmac.new(
        settings.resolved_otp_hmac_secret.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()


def secure_compare(left: str, right: str) -> bool:
    return hmac.compare_digest(left, right)
