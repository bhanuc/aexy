"""`X-Forwarded-For` counts only when a proxy we expect appended it.

Two identical copies of `get_client_ip` used to return the leftmost value of
the header to anyone who sent one. That value is client-controlled, so every
per-IP rate limit keyed on it could be reset per request just by changing the
header, and every audited `ip_address` was whatever the caller typed.
"""

from __future__ import annotations

import pytest

from aexy.core import client_ip as client_ip_module
from aexy.core.client_ip import get_client_ip


class _FakeClient:
    def __init__(self, host: str) -> None:
        self.host = host


class _FakeRequest:
    def __init__(self, peer: str | None, **headers: str) -> None:
        self.client = _FakeClient(peer) if peer else None
        self.headers = headers


@pytest.fixture
def trust(monkeypatch):
    """Configure which hops are ours."""
    def _set(*cidrs: str) -> None:
        monkeypatch.setattr(
            client_ip_module.settings, "trusted_proxies", ",".join(cidrs)
        )
    return _set


def test_forwarded_header_from_a_stranger_is_ignored(trust):
    """The bypass: a direct caller inventing a header gets nothing."""
    trust()
    request = _FakeRequest("198.51.100.7", **{"X-Forwarded-For": "1.2.3.4"})
    assert get_client_ip(request) == "198.51.100.7"


def test_rotating_a_forged_header_cannot_split_the_bucket(trust):
    """Same caller, three forged headers, one rate-limit identity."""
    trust()
    seen = {
        get_client_ip(
            _FakeRequest("198.51.100.7", **{"X-Forwarded-For": forged})
        )
        for forged in ("1.2.3.4", "5.6.7.8", "9.10.11.12")
    }
    assert seen == {"198.51.100.7"}


def test_trusted_proxy_hop_is_honoured(trust):
    trust("10.0.0.0/8")
    request = _FakeRequest("10.0.0.5", **{"X-Forwarded-For": "203.0.113.9"})
    assert get_client_ip(request) == "203.0.113.9"


def test_chained_proxies_yield_the_last_untrusted_hop(trust):
    """Hops left of our own infrastructure are still caller-supplied."""
    trust("10.0.0.0/8")
    request = _FakeRequest(
        "10.0.0.5",
        **{"X-Forwarded-For": "1.1.1.1, 203.0.113.9, 10.0.0.9"},
    )
    assert get_client_ip(request) == "203.0.113.9"


def test_trusted_proxy_with_no_header_falls_back_to_the_peer(trust):
    trust("10.0.0.0/8")
    assert get_client_ip(_FakeRequest("10.0.0.5")) == "10.0.0.5"


def test_real_ip_is_only_read_behind_a_trusted_proxy(trust):
    trust("10.0.0.0/8")
    behind = _FakeRequest("10.0.0.5", **{"X-Real-IP": "203.0.113.9"})
    assert get_client_ip(behind) == "203.0.113.9"

    trust()
    direct = _FakeRequest("198.51.100.7", **{"X-Real-IP": "203.0.113.9"})
    assert get_client_ip(direct) == "198.51.100.7"


def test_garbage_entries_do_not_open_the_gate(trust):
    """A malformed trusted_proxies entry is dropped, not treated as a wildcard."""
    trust("not-an-ip", "10.0.0.0/8")
    assert get_client_ip(
        _FakeRequest("198.51.100.7", **{"X-Forwarded-For": "1.2.3.4"})
    ) == "198.51.100.7"
    assert get_client_ip(
        _FakeRequest("10.0.0.5", **{"X-Forwarded-For": "1.2.3.4"})
    ) == "1.2.3.4"


def test_no_peer_at_all(trust):
    trust()
    assert get_client_ip(_FakeRequest(None)) == "unknown"
