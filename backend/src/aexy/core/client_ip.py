"""Who the caller actually is, for rate limiting and audit.

`X-Forwarded-For` is just a request header: any client can send one, and only
the hop that appended it can vouch for it. Honouring it unconditionally — which
is what two copies of this helper used to do — meant every per-IP rate limit in
the app could be bypassed by rotating the header between requests, and every
audited `ip_address` was caller-controlled text.

So the header is trusted only when the socket peer is a proxy we were told to
expect (`TRUSTED_PROXIES`). With none configured the socket peer wins, which is
correct for a directly-exposed service and safely over-restrictive for a
proxied one — limits bucket too coarsely rather than not at all.
"""

from __future__ import annotations

import ipaddress

from fastapi import Request

from aexy.core.config import settings

UNKNOWN = "unknown"


def _is_trusted_proxy(host: str) -> bool:
    networks = settings.trusted_proxy_networks
    if not networks:
        return False
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(addr in net for net in networks)


def get_client_ip(request: Request) -> str:
    """Best honest answer for the caller's IP.

    Walks `X-Forwarded-For` right-to-left, discarding hops we trust, and
    returns the first one we don't — that is the earliest address our own
    infrastructure can actually attest to. Anything further left was supplied
    by the client and is ignored.
    """
    peer = request.client.host if request.client else None

    if peer and _is_trusted_proxy(peer):
        forwarded = request.headers.get("X-Forwarded-For", "")
        hops = [h.strip() for h in forwarded.split(",") if h.strip()]
        while hops:
            candidate = hops.pop()
            if not _is_trusted_proxy(candidate):
                return candidate
        # Every hop was a proxy of ours, or the header was absent: the nearest
        # proxy is the most specific thing we can honestly name.
        real_ip = request.headers.get("X-Real-IP", "").strip()
        if real_ip and not _is_trusted_proxy(real_ip):
            return real_ip
        return peer

    return peer or UNKNOWN
