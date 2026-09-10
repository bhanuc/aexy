"""OpenObserve alert payload adapter.

OpenObserve delivers alerts via a Destination (webhook) + a Template that
renders a JSON body. We document a recommended template (see
docs/integrations/openobserve.md) but stay tolerant of field-name variations
since operators customize templates freely.
"""

import re
from datetime import datetime, timezone

from aexy.integrations.alert_providers.base import AlertContext, AlertProviderAdapter
from aexy.models.ticketing import TicketSeverity

# Map assorted upstream severity spellings onto our four levels.
_SEVERITY_MAP = {
    "critical": TicketSeverity.CRITICAL,
    "crit": TicketSeverity.CRITICAL,
    "fatal": TicketSeverity.CRITICAL,
    "emergency": TicketSeverity.CRITICAL,
    "error": TicketSeverity.HIGH,
    "high": TicketSeverity.HIGH,
    "sev1": TicketSeverity.CRITICAL,
    "sev2": TicketSeverity.HIGH,
    "warn": TicketSeverity.MEDIUM,
    "warning": TicketSeverity.MEDIUM,
    "medium": TicketSeverity.MEDIUM,
    "sev3": TicketSeverity.MEDIUM,
    "info": TicketSeverity.LOW,
    "low": TicketSeverity.LOW,
    "debug": TicketSeverity.LOW,
    "sev4": TicketSeverity.LOW,
}

# Values OpenObserve emits when a recovery/resolved alert fires.
_RECOVERY_VALUES = {"resolved", "recovered", "ok", "cleared", "recovery"}

# trace_id=<hex> / "trace_id": "<hex>" / traceId=<hex> — OTel style.
_TRACE_RE = re.compile(r'trace[_-]?id["\s:=]+([0-9a-fA-F]{8,32})')

_MAX_LOG_LINES = 50
_MAX_LOG_CHARS = 32_000


# A value the sender's own template failed to substitute: "{service}",
# "{{alert_name}}", "$service". OpenObserve passes an unknown variable through
# verbatim, so a Destination Template naming a field OpenObserve does not
# provide arrives as the placeholder itself — which is how tickets came to be
# titled "[MEDIUM] {service}: error-spike".
#
# Treated as absent rather than cleaned, so the caller's fallback chain does the
# work: `service` falls through to `stream_name` and finally to "unknown", which
# is a true statement. Same principle as `strip_merge_tags` on the outbound
# side — never emit a placeholder, wherever the text came from.
_PLACEHOLDER_RE = re.compile(r"^\s*(?:\{\{?[\w.\-]+\}?\}|\$\{?[\w.\-]+\}?)\s*$")


def _is_placeholder(value) -> bool:
    return isinstance(value, str) and bool(_PLACEHOLDER_RE.match(value))


def _first(payload: dict, *keys: str, default=None):
    """Return the first present, non-empty, non-placeholder value among ``keys``."""
    for k in keys:
        v = payload.get(k)
        if v in (None, "") or _is_placeholder(v):
            continue
        return v
    return default


class OpenObserveAdapter(AlertProviderAdapter):
    provider = "openobserve"

    def normalize(self, payload: dict) -> AlertContext:
        if not isinstance(payload, dict):
            raise ValueError("payload is not a JSON object")

        alert_name = _first(payload, "alert_name", "alertName", "name", "title")
        if not alert_name:
            raise ValueError("missing alert name")

        # Service: explicit field, else the stream name, else 'unknown'.
        service = _first(
            payload, "service", "service_name", "microservice", "stream", "stream_name",
            default="unknown",
        )

        severity_raw = str(_first(payload, "severity", "level", "priority", default="medium")).lower()
        severity = _SEVERITY_MAP.get(severity_raw, TicketSeverity.MEDIUM)

        status_raw = str(_first(payload, "status", "state", default="")).lower()
        is_recovery = status_raw in _RECOVERY_VALUES

        environment = _first(payload, "environment", "env", "namespace")
        alert_url = _first(payload, "alert_url", "alertUrl", "url", "source_url")

        log_lines = self._extract_log_lines(payload)
        trace_ids = self._extract_trace_ids(payload, log_lines)
        started_at = self._parse_time(_first(payload, "start_time", "alert_start_time", "timestamp"))

        extra = {
            "org": _first(payload, "org", "org_name", "organization"),
            "stream": _first(payload, "stream", "stream_name"),
            "alert_type": _first(payload, "alert_type", "alertType"),
            "match_count": _first(payload, "count", "alert_count", "hits"),
        }
        extra = {k: v for k, v in extra.items() if v is not None}

        return AlertContext(
            provider=self.provider,
            alert_name=str(alert_name),
            service=str(service),
            severity=severity,
            environment=str(environment) if environment else None,
            log_lines=log_lines,
            alert_url=str(alert_url) if alert_url else None,
            trace_ids=trace_ids,
            started_at=started_at,
            is_recovery=is_recovery,
            extra=extra,
        )

    def _extract_log_lines(self, payload: dict) -> list[str]:
        """Pull matched log rows from the payload, capped in count and size."""
        rows = _first(payload, "rows", "logs", "records", "matches", default=None)
        lines: list[str] = []

        if isinstance(rows, str):
            lines = [ln for ln in rows.splitlines() if ln.strip()]
        elif isinstance(rows, list):
            for row in rows:
                if isinstance(row, str):
                    lines.append(row)
                elif isinstance(row, dict):
                    # Prefer a message-like field, else serialize the row.
                    msg = _first(row, "message", "log", "msg", "body")
                    lines.append(str(msg) if msg is not None else str(row))
                else:
                    lines.append(str(row))

        # Cap total size to keep tickets and JSONB reasonable.
        capped: list[str] = []
        total = 0
        for ln in lines[:_MAX_LOG_LINES]:
            ln = ln[:2000]
            if total + len(ln) > _MAX_LOG_CHARS:
                capped.append("... (truncated, see source alert)")
                break
            capped.append(ln)
            total += len(ln)
        if len(lines) > _MAX_LOG_LINES:
            capped.append(f"... ({len(lines) - _MAX_LOG_LINES} more lines omitted)")
        return capped

    def _extract_trace_ids(self, payload: dict, log_lines: list[str]) -> list[str]:
        explicit = _first(payload, "trace_id", "traceId", "trace_ids", default=None)
        found: list[str] = []
        if isinstance(explicit, str):
            found.append(explicit)
        elif isinstance(explicit, list):
            found.extend(str(t) for t in explicit)

        for line in log_lines:
            found.extend(_TRACE_RE.findall(line))

        # De-dupe, preserve order, cap.
        seen: set[str] = set()
        result: list[str] = []
        for t in found:
            if t and t not in seen:
                seen.add(t)
                result.append(t)
        return result[:20]

    def _parse_time(self, value) -> datetime:
        now = datetime.now(timezone.utc)
        if value is None:
            return now
        # Numeric epoch (seconds / millis / micros).
        try:
            num = float(value)
            if num > 1e14:      # microseconds
                num /= 1_000_000
            elif num > 1e11:    # milliseconds
                num /= 1000
            return datetime.fromtimestamp(num, tz=timezone.utc)
        except (TypeError, ValueError):
            pass
        # ISO 8601.
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return now
