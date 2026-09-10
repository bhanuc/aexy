"""The data an Incidents screen needs, and the gaps that made it impossible.

An OpenObserve integration had been ingesting cleanly for two months — 430
events, no errors — and nobody could find the three tickets it produced. Part
of that was navigation, but part was that the API could not answer the
questions an incident queue asks:

* "Show me the critical ones" — ``TicketFilters.severity`` was declared and
  ``list_tickets`` silently ignored it.
* "Show me alerts, not form submissions" — ``source`` existed only as a
  negative module boundary, never as a filter.
* "Worst first" / "most recently seen first" — ordering was hardcoded to
  ``created_at DESC``.
* "How bad, how often, how recently" — ``severity`` was returned but
  ``occurrence_count``, ``last_seen_at`` and ``source`` were not, so the
  columns could not be rendered at all.

And two things that made the tickets themselves useless: they landed on a form
with no matching fields, and their titles carried an unsubstituted template
placeholder.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.integrations.alert_providers.openobserve import (
    OpenObserveAdapter,
    _is_placeholder,
)
from aexy.models.developer import Developer
from aexy.models.ticketing import SLAPolicy, Ticket, TicketForm
from aexy.models.workspace import Workspace, WorkspaceMember
from aexy.schemas.ticketing import TicketFilters
from aexy.services.ticket_service import TicketService

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)


class _Shop:
    ws: Workspace
    owner: Developer
    form: TicketForm


async def _shop(db: AsyncSession, slug: str) -> _Shop:
    d = _Shop()
    d.owner = Developer(id=str(uuid4()), email=f"o-{slug}@d.example", name="Owner")
    db.add(d.owner)
    await db.flush()
    d.ws = Workspace(
        id=str(uuid4()), name=f"WS {slug}", slug=slug, owner_id=d.owner.id, settings={}
    )
    db.add(d.ws)
    await db.flush()
    db.add(
        WorkspaceMember(
            id=str(uuid4()), workspace_id=d.ws.id, developer_id=d.owner.id, role="member"
        )
    )
    d.form = TicketForm(
        id=str(uuid4()), workspace_id=d.ws.id, name="Bug Report", slug=f"bug-{slug}",
        created_by_id=d.owner.id,
    )
    db.add(d.form)
    await db.flush()
    await db.commit()
    return d


async def _ticket(
    db: AsyncSession,
    d: _Shop,
    number: int,
    *,
    source: str | None,
    severity: str | None = None,
    occurrences: int = 1,
    last_seen: datetime | None = None,
) -> Ticket:
    t = Ticket(
        id=str(uuid4()),
        workspace_id=d.ws.id,
        form_id=d.form.id,
        ticket_number=number,
        title=f"ticket {number}",
        status="new",
        source=source,
        severity=severity,
        occurrence_count=occurrences,
        last_seen_at=last_seen,
        field_values={},
    )
    db.add(t)
    await db.flush()
    return t


async def _numbers(db: AsyncSession, d: _Shop, **filter_kwargs) -> list[int]:
    tickets, _ = await TicketService(db).list_tickets(
        d.ws.id, filters=TicketFilters(**filter_kwargs)
    )
    return [t.ticket_number for t in tickets]


# ==================================================== the placeholder in titles


@pytest.mark.parametrize(
    "value", ["{service}", "{{alert_name}}", "${service}", "$service", " {service} "]
)
def test_an_unsubstituted_placeholder_is_not_a_value(value: str) -> None:
    """Tickets read ``[MEDIUM] {service}: error-spike`` on the live desk.

    OpenObserve passes an unknown template variable through verbatim, so a
    Destination Template naming a field it does not provide arrives as the
    placeholder itself.
    """
    assert _is_placeholder(value) is True


@pytest.mark.parametrize("value", ["payments-api", "unknown", "", "prod-logs", "5xx"])
def test_a_real_value_is_left_alone(value: str) -> None:
    assert _is_placeholder(value) is False


def test_a_placeholder_falls_through_to_the_next_source() -> None:
    """Treated as absent rather than scrubbed, so the fallback chain does the work.

    ``service`` already falls back to the stream name and finally to "unknown" —
    all three are true statements, which ``{service}`` is not.
    """
    ctx = OpenObserveAdapter().normalize(
        {
            "alert_name": "error-spike",
            "service": "{service}",
            "stream_name": "prod-logs",
            "severity": "medium",
        }
    )
    assert ctx.service == "prod-logs"
    assert "{" not in f"[{ctx.severity.value.upper()}] {ctx.service}: {ctx.alert_name}"


def test_with_no_fallback_it_becomes_unknown_not_a_placeholder() -> None:
    ctx = OpenObserveAdapter().normalize(
        {"alert_name": "error-spike", "service": "{service}"}
    )
    assert ctx.service == "unknown"


# ================================================================== the filters


@pytest.mark.asyncio
async def test_severity_actually_filters_now(db_session: AsyncSession) -> None:
    """It was on the schema and never translated into a clause.

    A filter the API accepted, documented and silently ignored — so "show me
    the critical incidents" returned everything.
    """
    d = await _shop(db_session, "inc-sev")
    await _ticket(db_session, d, 1, source="openobserve", severity="critical")
    await _ticket(db_session, d, 2, source="openobserve", severity="low")
    await db_session.commit()

    assert await _numbers(db_session, d, severity=["critical"]) == [1]


@pytest.mark.asyncio
async def test_source_selects_alerts_and_submissions_apart(
    db_session: AsyncSession,
) -> None:
    """The two lists the Incidents item shows, from one table."""
    d = await _shop(db_session, "inc-source")
    await _ticket(db_session, d, 1, source="openobserve")
    await _ticket(db_session, d, 2, source=None)
    await _ticket(db_session, d, 3, source="form")
    await db_session.commit()

    assert await _numbers(db_session, d, source=["openobserve"]) == [1]
    # A submissions list needs both: most form rows record no source at all, and
    # a list of values cannot express null.
    assert sorted(
        await _numbers(db_session, d, source=["form"], source_is_null=True)
    ) == [2, 3]


@pytest.mark.asyncio
async def test_service_desk_rows_stay_out_whatever_is_asked(
    db_session: AsyncSession,
) -> None:
    """That boundary is not a filter and is not the caller's to lift."""
    d = await _shop(db_session, "inc-boundary")
    await _ticket(db_session, d, 1, source="openobserve")
    await _ticket(db_session, d, 2, source="service_desk_gmail")
    await db_session.commit()

    assert await _numbers(db_session, d) == [1]
    assert await _numbers(db_session, d, source=["service_desk_gmail"]) == []


# ================================================================== the sorting


@pytest.mark.asyncio
async def test_severity_sorts_worst_first_and_unset_last(
    db_session: AsyncSession,
) -> None:
    """Words in a column sort alphabetically, which is nearly the worst order.

    "critical" above "high" above "low" above "medium" is what the raw column
    gives. And an absent severity is nobody having said, not "less severe than
    low", so it belongs at the bottom whichever way the arrow points.
    """
    d = await _shop(db_session, "inc-sort-sev")
    await _ticket(db_session, d, 1, source="openobserve", severity="medium")
    await _ticket(db_session, d, 2, source="openobserve", severity=None)
    await _ticket(db_session, d, 3, source="openobserve", severity="critical")
    await _ticket(db_session, d, 4, source="openobserve", severity="low")
    await db_session.commit()

    assert await _numbers(db_session, d, sort="severity", direction="desc") == [3, 1, 4, 2]
    assert await _numbers(db_session, d, sort="severity", direction="asc") == [4, 1, 3, 2]


@pytest.mark.asyncio
async def test_last_seen_sorts_live_incidents_above_quiet_ones(
    db_session: AsyncSession,
) -> None:
    """What `created_at` cannot express.

    An incident that fired a minute ago outranks one that opened last week and
    has been silent since — and a ticket nobody has seen recur belongs at the
    bottom, not the top.
    """
    d = await _shop(db_session, "inc-sort-seen")
    await _ticket(db_session, d, 1, source="openobserve", last_seen=NOW - timedelta(days=7))
    await _ticket(db_session, d, 2, source="openobserve", last_seen=None)
    await _ticket(db_session, d, 3, source="openobserve", last_seen=NOW)
    await db_session.commit()

    assert await _numbers(db_session, d, sort="last_seen", direction="desc") == [3, 1, 2]


@pytest.mark.asyncio
async def test_occurrences_sorts_by_how_noisy(db_session: AsyncSession) -> None:
    d = await _shop(db_session, "inc-sort-occ")
    await _ticket(db_session, d, 1, source="openobserve", occurrences=3)
    await _ticket(db_session, d, 2, source="openobserve", occurrences=131)
    await db_session.commit()

    assert await _numbers(db_session, d, sort="occurrences", direction="desc") == [2, 1]


@pytest.mark.asyncio
async def test_ordering_is_stable_inside_a_band(db_session: AsyncSession) -> None:
    """Four severity values across many rows means most rows tie.

    Without a tiebreaker the order inside a band shuffles between pages and the
    same ticket shows up twice.
    """
    d = await _shop(db_session, "inc-stable")
    for n in range(1, 6):
        await _ticket(db_session, d, n, source="openobserve", severity="high")
    await db_session.commit()

    first = await _numbers(db_session, d, sort="severity")
    assert first == await _numbers(db_session, d, sort="severity")
    assert len(set(first)) == 5


# ============================================================ SLA for an alert


@pytest.mark.asyncio
async def test_a_policy_can_match_on_severity(db_session: AsyncSession) -> None:
    """An alert has no submitter and no meaningful form beyond "the incident form".

    Its priority is derived from its severity anyway, so severity is the axis an
    on-call commitment is actually written against.
    """
    d = await _shop(db_session, "inc-sla")
    db_session.add(
        SLAPolicy(
            id=str(uuid4()),
            workspace_id=d.ws.id,
            name="Incident — critical",
            conditions={"severities": ["critical"]},
            first_response_target_minutes=30,
            priority_order=10,
        )
    )
    await db_session.commit()

    critical = await _ticket(db_session, d, 1, source="openobserve", severity="critical")
    low = await _ticket(db_session, d, 2, source="openobserve", severity="low")
    service = TicketService(db_session)
    await service.apply_sla(critical)
    await service.apply_sla(low)
    await db_session.commit()

    assert critical.sla_due_at is not None
    # The policy names one severity, so it must not silently cover the others.
    assert low.sla_due_at is None


@pytest.mark.asyncio
async def test_no_matching_policy_leaves_no_clock(db_session: AsyncSession) -> None:
    """Wiring the alert path to `apply_sla` does nothing on its own.

    `sla_due_at` is only ever set by a *matching* policy, which is why the
    integration seeds one on connect — otherwise the SLA column reads empty
    forever and nothing ever breaches.
    """
    d = await _shop(db_session, "inc-sla-none")
    t = await _ticket(db_session, d, 1, source="openobserve", severity="critical")
    await TicketService(db_session).apply_sla(t)
    await db_session.commit()

    assert t.sla_due_at is None


# ============================================ intake, and the service column


@pytest.mark.asyncio
async def test_intake_alerts_needs_no_provider_list_from_the_caller(
    db_session: AsyncSession,
) -> None:
    """The provider slugs were written out in three places at once.

    The `AlertProvider` enum, a SQL migration, and a frontend constant — so
    adding a provider meant a frontend release to make its tickets visible.
    `intake` asks the question instead and the server resolves it.
    """
    d = await _shop(db_session, "inc-intake-a")
    await _ticket(db_session, d, 1, source="openobserve")
    await _ticket(db_session, d, 2, source="sentry")
    await _ticket(db_session, d, 3, source=None)
    await _ticket(db_session, d, 4, source="form")
    await db_session.commit()

    assert sorted(await _numbers(db_session, d, intake="alerts")) == [1, 2]


@pytest.mark.asyncio
async def test_intake_submissions_is_everything_that_is_not_an_alert(
    db_session: AsyncSession,
) -> None:
    """Including rows with no source at all, which most form submissions are."""
    d = await _shop(db_session, "inc-intake-s")
    await _ticket(db_session, d, 1, source="openobserve")
    await _ticket(db_session, d, 2, source=None)
    await _ticket(db_session, d, 3, source="form")
    await db_session.commit()

    assert sorted(await _numbers(db_session, d, intake="submissions")) == [2, 3]


@pytest.mark.asyncio
async def test_intake_covers_every_provider_the_enum_defines(
    db_session: AsyncSession,
) -> None:
    """A provider added to the enum reaches the Alerts list with no other change."""
    from aexy.models.alerting import AlertProvider
    from aexy.services.ticket_service import _alert_sources

    assert _alert_sources() == [p.value for p in AlertProvider]

    d = await _shop(db_session, "inc-intake-all")
    for n, provider in enumerate(AlertProvider, start=1):
        await _ticket(db_session, d, n, source=provider.value)
    await db_session.commit()

    seen = await _numbers(db_session, d, intake="alerts")
    assert len(seen) == len(list(AlertProvider))


@pytest.mark.asyncio
async def test_the_affected_service_reaches_the_list(db_session: AsyncSession) -> None:
    """The first column anybody looks for in an alert queue.

    It lives in `field_values`, which a list response deliberately does not
    carry — returning whole JSONB blobs for a table is how a list gets slow.
    Lifted out as one string so the column can exist at all.
    """
    from aexy.api.tickets import ticket_to_list_response

    d = await _shop(db_session, "inc-service")
    t = await _ticket(db_session, d, 1, source="openobserve", severity="high")
    # The alert path writes no `title` column — the headline goes into
    # field_values — so the fixture has to be null here or it is not testing
    # the case that matters.
    t.title = None
    t.field_values = {"title": "[HIGH] payments-api: 5xx spike", "service_name": "payments-api"}
    await db_session.commit()

    # Through the real query, which eager-loads the two relationships the
    # serializer reads. Constructing a bare row and serializing it raises
    # MissingGreenlet on the first lazy access under async SQLAlchemy.
    rows, _ = await TicketService(db_session).list_tickets(
        d.ws.id, filters=TicketFilters(intake="alerts")
    )
    row = ticket_to_list_response(rows[0])
    assert row.service_name == "payments-api"
    # And the headline survives the alert path never setting the title column.
    assert row.title == "[HIGH] payments-api: 5xx spike"


@pytest.mark.asyncio
async def test_a_submission_has_no_service_and_says_so(
    db_session: AsyncSession,
) -> None:
    from aexy.api.tickets import ticket_to_list_response

    d = await _shop(db_session, "inc-service-none")
    await _ticket(db_session, d, 1, source=None)
    await db_session.commit()

    rows, _ = await TicketService(db_session).list_tickets(
        d.ws.id, filters=TicketFilters(intake="submissions")
    )
    assert ticket_to_list_response(rows[0]).service_name is None
