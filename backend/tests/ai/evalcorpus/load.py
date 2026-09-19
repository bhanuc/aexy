"""Turn the shape into rows.

The facts come from `shape.py` and the text from `data/prose.json`; this module
only knows how to write them down. Keeping it that way is deliberate — the
loader must be exercisable with stub text, because otherwise nothing structural
can be tested until a model has been run.

Two things here are not bookkeeping.

**The taxonomy is seeded by the product, not by us.** `seed_taxonomy` is what the
application itself calls, so the stakeholder and request-type rows are the ones a
real desk would have — including which bucket is terminal, which is the only
reason `is_open` means anything (`service_desk_service.py:2091-2100`).

**A desk ticket is two rows.** `aexy_sd_open_tickets` reads
`ServiceDeskTicket ⋈ Ticket`, so writing a `Ticket` alone produces a ticket that
every desk query silently skips. That is exactly what `ask_eval_seed.py` did, and
why the tool answered `[]` against a workspace that looked populated.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.models.compliance import MandatoryTraining, TrainingAssignment
from aexy.models.crm import CRMObject, CRMRecord
from aexy.models.developer import Developer
from aexy.models.leave import LeaveRequest, LeaveType
from aexy.models.organization import Department, DepartmentMember
from aexy.models.service_desk import (
    ServiceDeskAccount,
    ServiceDeskTicket,
    TicketPendingSegment,
)
from aexy.models.sprint import Sprint, SprintTask
from aexy.models.team import Team
from aexy.models.ticketing import Ticket, TicketForm
from aexy.models.tracking import Blocker
from aexy.models.uptime import UptimeIncident, UptimeMonitor
from aexy.models.workspace import Workspace, WorkspaceMember
from aexy.services.crm_service import CRMObjectService
from aexy.services.service_desk_industry_templates import get_template
from aexy.services.service_desk_taxonomy import seed_taxonomy
from tests.ai.evalcorpus import shape
from tests.ai.evalcorpus.ids import corpus_id

PROSE_FILE = Path(__file__).parent / "data" / "prose.json"

WORKSPACE_ID = corpus_id("workspace", "aexyeval")
WORKSPACE_NAME = "AexyEval Workspace"


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Clock:
    """One anchor for the whole load.

    Rows in `shape.py` are offsets, and they are resolved against a single
    instant captured once. Two properties fall out, both of which the benchmark
    needs. Every row agrees about what "now" was, so "created this week" is
    answerable — a seeder that calls `datetime.now()` per row, as
    `seed_marketing_demo.py:69` does, cannot promise that. And the *meaning* of a
    row is stable over calendar time: a certificate 20 days from expiry is still
    20 days from expiry next month, where a pinned date would have gone stale and
    the case would have quietly stopped testing anything.
    """

    anchor: datetime

    @classmethod
    def now(cls) -> Clock:
        # Truncated to the hour so a load is reproducible within a session and
        # timestamps in a failure message are readable.
        return cls(datetime.now(UTC).replace(minute=0, second=0, microsecond=0))

    def days_ago(self, days: int) -> datetime:
        return self.anchor - timedelta(days=days)

    def days_ahead(self, days: int) -> datetime:
        return self.anchor + timedelta(days=days)


# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------


class Prose:
    """The frozen text, looked up by (section, slug, field)."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    @classmethod
    def from_file(cls, path: Path = PROSE_FILE) -> Prose:
        if not path.exists():
            raise FileNotFoundError(
                f"{path} does not exist. The corpus text is generated once and "
                f"committed — run `python scripts/generate_eval_corpus.py "
                f"--refresh` with a model available."
            )
        return cls(json.loads(path.read_text()))

    @classmethod
    def stub(cls) -> Prose:
        """Placeholder text, for exercising structure without a model.

        The loader must be testable before anyone has run
        `generate_eval_corpus.py`, and the structural properties worth testing —
        that a desk ticket is two rows, that `is_open` resolves through the
        taxonomy, that the counts come back — do not depend on a word of it.
        Never use this to load a corpus a model is graded against: the text is
        the half that makes the world readable.
        """
        return cls({})

    def get(self, section: str, slug: str, field_name: str) -> str:
        if not self._data:
            return f"{section}.{slug}.{field_name}"
        try:
            return self._data[section][slug][field_name]
        except KeyError as exc:
            raise KeyError(
                f"no {field_name!r} for {section}.{slug} in the corpus text; "
                f"regenerate it (missing key {exc})"
            ) from None


# ---------------------------------------------------------------------------
# What a load produced
# ---------------------------------------------------------------------------


@dataclass
class LoadedCorpus:
    workspace_id: str
    caller_id: str
    team_id: str
    people: dict[str, str] = field(default_factory=dict)
    accounts: dict[str, str] = field(default_factory=dict)
    tickets: dict[str, str] = field(default_factory=dict)
    sprints: dict[str, str] = field(default_factory=dict)
    tasks: dict[str, str] = field(default_factory=dict)
    blockers: dict[str, str] = field(default_factory=dict)
    monitors: dict[str, str] = field(default_factory=dict)
    incidents: dict[str, str] = field(default_factory=dict)
    leave_requests: dict[str, str] = field(default_factory=dict)
    trainings: dict[str, str] = field(default_factory=dict)
    crm_records: dict[str, str] = field(default_factory=dict)
    crm_object_id: str | None = None


# ---------------------------------------------------------------------------
# The load
# ---------------------------------------------------------------------------


async def load_corpus(
    db: AsyncSession,
    *,
    prose: Prose,
    clock: Clock | None = None,
) -> LoadedCorpus:
    """Write the corpus into `db` and return the ids it used.

    Returns early if the workspace is already there, so a persistent eval
    database can be re-used without duplicating every ticket — the same
    lookup-before-write rule the repo's seed scripts follow.
    """
    clock = clock or Clock.now()

    existing = await db.get(Workspace, WORKSPACE_ID)
    if existing is not None:
        return await _describe(db)

    caller = _add_people(db, prose)
    await db.flush()

    workspace = Workspace(
        id=WORKSPACE_ID,
        name=WORKSPACE_NAME,
        slug="aexyeval-workspace",
        type="internal",
        owner_id=caller,
        settings={},
        is_active=True,
    )
    db.add(workspace)
    await db.flush()

    _add_memberships(db)
    team_id = _add_team(db)
    _add_departments(db)
    await db.flush()

    # The product's own seeder, so the desk has the buckets a real one has.
    template = get_template(shape.TEMPLATE_SLUG)
    await seed_taxonomy(db, WORKSPACE_ID, template)
    await db.flush()

    _add_accounts(db, prose)
    form_id = _add_ticket_form(db, caller)
    await db.flush()

    await _add_tickets(db, prose, clock, form_id)
    _add_sprints(db, prose, clock, team_id, caller)
    await db.flush()

    _add_tasks(db, prose, team_id)
    _add_blockers(db, prose, clock, team_id)
    await _add_uptime(db, prose, clock, caller)
    await _add_leave(db, clock)
    await _add_compliance(db, prose, clock, caller)
    await _add_crm(db, prose, caller)
    await db.commit()

    return await _describe(db)


def _add_people(db: AsyncSession, prose: Prose) -> str:
    for person in shape.PEOPLE:
        db.add(
            Developer(
                id=person.id,
                email=person.email,
                name=prose.get("people", person.slug, "name"),
                has_completed_onboarding=True,
                account_type="internal",
            )
        )
    return shape.CALLER.id


def _add_memberships(db: AsyncSession) -> None:
    for person in shape.PEOPLE:
        # `status="active"` is load-bearing: anything else resolves to zero
        # capabilities, so the model would be offered no tools at all
        # (`app_access_service.py:364`).
        db.add(
            WorkspaceMember(
                id=corpus_id("member", person.slug),
                workspace_id=WORKSPACE_ID,
                developer_id=person.id,
                role=person.role,
                status="active",
            )
        )


def _add_team(db: AsyncSession) -> str:
    team_id = corpus_id("team", "platform")
    db.add(
        Team(
            id=team_id,
            workspace_id=WORKSPACE_ID,
            name="Platform",
            slug="platform",
            type="manual",
            auto_sync_enabled=False,
            settings={},
            is_active=True,
        )
    )
    return team_id


def _add_departments(db: AsyncSession) -> None:
    """Departments for the people who have a desk function.

    The caller is deliberately left out. A member's app access is resolved from
    the union of their departments' `app_config` when they have one, and from a
    permissive fallback when nobody has configured anything
    (`app_access_service.py:459-474`). Leaving the caller unprofiled keeps them
    on the fallback, which offers every tool — the harder setting to benchmark
    against, and the one the corpus is documented to use.
    """
    functions = {p.function for p in shape.PEOPLE if p.function}
    for function in sorted(functions):
        department_id = corpus_id("department", function)
        db.add(
            Department(
                id=department_id,
                workspace_id=WORKSPACE_ID,
                name=function.title(),
                slug=function,
                function_key=function,
                path=function,
                depth=0,
                position=0,
                is_active=True,
                settings={},
                app_config={},
            )
        )
        for person in shape.PEOPLE:
            if person.function != function:
                continue
            db.add(
                DepartmentMember(
                    id=corpus_id("department-member", f"{function}/{person.slug}"),
                    workspace_id=WORKSPACE_ID,
                    department_id=department_id,
                    developer_id=person.id,
                    role_in_department="member",
                    is_primary=True,
                )
            )


def _add_accounts(db: AsyncSession, prose: Prose) -> None:
    for account in shape.ACCOUNTS:
        db.add(
            ServiceDeskAccount(
                id=account.id,
                workspace_id=WORKSPACE_ID,
                name=prose.get("accounts", account.slug, "name"),
                is_active=True,
            )
        )


def _add_ticket_form(db: AsyncSession, caller_id: str) -> str:
    form_id = corpus_id("ticket-form", "support")
    db.add(
        TicketForm(
            id=form_id,
            workspace_id=WORKSPACE_ID,
            name="Support",
            slug="support",
            public_url_token=corpus_id("ticket-form-token", "support").replace("-", ""),
            is_active=True,
            auth_mode="anonymous",
            require_email=True,
            theme={},
            destinations=[],
            conditional_rules=[],
            created_by_id=caller_id,
        )
    )
    return form_id


async def _add_tickets(
    db: AsyncSession, prose: Prose, clock: Clock, form_id: str
) -> None:
    """Tickets first, then the two tables that point at them.

    The flush in the middle is required, not tidiness. SQLAlchemy orders inserts
    from the *relationships* between mappers, and `ServiceDeskTicket` and
    `TicketPendingSegment` reach `tickets` through plain foreign-key columns with
    no relationship declared back this way — so the unit of work has no edge to
    sort on and is free to write a segment before the ticket it belongs to.
    """
    people = {p.slug: p.id for p in shape.PEOPLE}
    accounts = {a.slug: a.id for a in shape.ACCOUNTS}

    for number, ticket in enumerate(shape.TICKETS, start=1):
        created = clock.days_ago(ticket.age_days)
        db.add(
            Ticket(
                id=ticket.id,
                form_id=form_id,
                workspace_id=WORKSPACE_ID,
                ticket_number=number,
                title=prose.get("tickets", ticket.slug, "subject"),
                field_values={
                    "subject": prose.get("tickets", ticket.slug, "subject"),
                    "body": prose.get("tickets", ticket.slug, "body"),
                },
                attachments=[],
                external_issues=[],
                status=ticket.status,
                priority=ticket.priority,
                severity=ticket.severity,
                assignee_id=people[ticket.assignee] if ticket.assignee else None,
                created_at=created,
                updated_at=created,
            )
        )
    await db.flush()

    for ticket in shape.TICKETS:
        created = clock.days_ago(ticket.age_days)
        # The desk half. Without it the ticket exists and no desk query sees it.
        db.add(
            ServiceDeskTicket(
                id=corpus_id("desk-ticket", ticket.slug),
                ticket_id=ticket.id,
                workspace_id=WORKSPACE_ID,
                request_type=ticket.request_type,
                pending_with=ticket.pending_with,
                origin="email",
                needs_triage=ticket.needs_triage,
                account_id=accounts[ticket.account],
                created_at=created,
                updated_at=created,
            )
        )
        # One open segment per ticket, so the hand-off ledger the TAT report
        # reads is present rather than empty. Richer histories belong with the
        # TAT cases themselves.
        db.add(
            TicketPendingSegment(
                id=corpus_id("segment", ticket.slug),
                workspace_id=WORKSPACE_ID,
                ticket_id=ticket.id,
                pending_with=ticket.pending_with,
                entered_at=created,
            )
        )


def _add_sprints(
    db: AsyncSession, prose: Prose, clock: Clock, team_id: str, caller_id: str
) -> None:
    for sprint in shape.SPRINTS:
        db.add(
            Sprint(
                id=sprint.id,
                team_id=team_id,
                workspace_id=WORKSPACE_ID,
                name=prose.get("sprints", sprint.slug, "name"),
                status=sprint.status,
                start_date=clock.days_ago(sprint.starts_days_ago),
                end_date=clock.days_ahead(sprint.ends_days_ahead),
                settings={},
                created_by_id=caller_id,
            )
        )


def _add_tasks(db: AsyncSession, prose: Prose, team_id: str) -> None:
    people = {p.slug: p.id for p in shape.PEOPLE}
    sprints = {s.slug: s.id for s in shape.SPRINTS}

    for task in shape.TASKS:
        db.add(
            SprintTask(
                id=task.id,
                sprint_id=sprints[task.sprint],
                team_id=team_id,
                workspace_id=WORKSPACE_ID,
                source_type="manual",
                source_id=task.slug,
                title=prose.get("tasks", task.slug, "title"),
                priority=task.priority,
                status=task.status,
                assignee_id=people[task.assignee] if task.assignee else None,
                story_points=task.story_points,
                labels=[],
                is_archived=False,
            )
        )


def _add_blockers(db: AsyncSession, prose: Prose, clock: Clock, team_id: str) -> None:
    people = {p.slug: p.id for p in shape.PEOPLE}
    for blocker in shape.BLOCKERS:
        reported = clock.days_ago(blocker.reported_days_ago)
        db.add(
            Blocker(
                id=blocker.id,
                developer_id=people[blocker.reporter],
                team_id=team_id,
                workspace_id=WORKSPACE_ID,
                description=prose.get("blockers", blocker.slug, "summary"),
                severity=blocker.severity,
                category="technical",
                status=blocker.status,
                source="manual",
                reported_at=reported,
                resolved_at=reported if blocker.status == "resolved" else None,
            )
        )


async def _describe(db: AsyncSession) -> LoadedCorpus:
    """The ids a caller needs, read back rather than assumed."""
    ticket_ids = set(
        (await db.execute(select(Ticket.id).where(Ticket.workspace_id == WORKSPACE_ID)))
        .scalars()
        .all()
    )
    return LoadedCorpus(
        workspace_id=WORKSPACE_ID,
        caller_id=shape.CALLER.id,
        team_id=corpus_id("team", "platform"),
        people={p.slug: p.id for p in shape.PEOPLE},
        accounts={a.slug: a.id for a in shape.ACCOUNTS},
        tickets={t.slug: t.id for t in shape.TICKETS if t.id in ticket_ids},
        sprints={s.slug: s.id for s in shape.SPRINTS},
        tasks={t.slug: t.id for t in shape.TASKS},
        blockers={b.slug: b.id for b in shape.BLOCKERS},
        monitors={m.slug: m.id for m in shape.MONITORS},
        incidents={i.slug: i.id for i in shape.INCIDENTS},
        leave_requests={r.slug: r.id for r in shape.LEAVE_REQUESTS},
        trainings={t.slug: t.id for t in shape.TRAININGS},
        crm_records={r.slug: r.id for r in shape.CRM_RECORDS},
        crm_object_id=(
            await db.execute(
                select(CRMObject.id).where(
                    CRMObject.workspace_id == WORKSPACE_ID,
                    CRMObject.object_type == shape.CRM_OBJECT_SLUG,
                )
            )
        ).scalar_one_or_none(),
    )


def resolve_corpus_refs(value: Any, corpus: LoadedCorpus) -> Any:
    """Replace `{"$corpus": "sprints.autumn-hardening"}` with the loaded id.

    A generated case cannot hard-code an id: `corpus_id` derives them from
    slugs, so they are stable, but writing them into the fixture would mean
    regenerating it whenever the id scheme changed, and would make the file
    unreadable. A case names the row it means and the harness looks it up
    against the corpus it actually loaded.
    """
    if isinstance(value, dict):
        reference = value.get("$corpus")
        if isinstance(reference, str):
            section, _, slug = reference.partition(".")
            target = getattr(corpus, section, None)
            if target is None:
                raise KeyError(f"no corpus attribute {section!r} (from {reference!r})")
            # A reference with no dot names a scalar the load produced — the id
            # of the one CRM object, say — rather than a row in a table.
            if not slug:
                return target
            if not isinstance(target, dict) or slug not in target:
                raise KeyError(f"no corpus row at {reference!r}")
            return target[slug]
        return {key: resolve_corpus_refs(item, corpus) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve_corpus_refs(item, corpus) for item in value]
    return value


async def _add_uptime(db: AsyncSession, prose: Prose, clock: Clock, caller_id: str) -> None:
    for monitor in shape.MONITORS:
        db.add(
            UptimeMonitor(
                id=monitor.id,
                workspace_id=WORKSPACE_ID,
                name=monitor.slug.replace("-", " ").title(),
                check_type="http",
                url=f"https://{monitor.slug}.example.com/health",
                expected_status_codes=[200],
                request_headers={},
                notification_channels=[],
                current_status=monitor.current_status,
                is_active=True,
                created_by_id=caller_id,
            )
        )
    await db.flush()

    for incident in shape.INCIDENTS:
        started = clock.days_ago(incident.started_days_ago)
        db.add(
            UptimeIncident(
                id=incident.id,
                monitor_id=corpus_id("monitor", incident.monitor),
                workspace_id=WORKSPACE_ID,
                status=incident.status,
                started_at=started,
                resolved_at=clock.days_ago(0) if incident.status == "resolved" else None,
                acknowledged_at=started if incident.acknowledged else None,
                acknowledged_by_id=caller_id if incident.acknowledged else None,
            )
        )


async def _add_leave(db: AsyncSession, clock: Clock) -> None:
    for slug in shape.LEAVE_TYPES:
        db.add(
            LeaveType(
                id=corpus_id("leave-type", slug),
                workspace_id=WORKSPACE_ID,
                name=slug.title(),
                slug=slug,
            )
        )
    await db.flush()

    people = {p.slug: p.id for p in shape.PEOPLE}
    for request in shape.LEAVE_REQUESTS:
        start = clock.days_ahead(request.starts_days_ahead).date()
        db.add(
            LeaveRequest(
                id=request.id,
                workspace_id=WORKSPACE_ID,
                developer_id=people[request.requester],
                leave_type_id=corpus_id("leave-type", request.leave_type),
                start_date=start,
                end_date=start + timedelta(days=int(request.days) - 1),
                total_days=request.days,
                status=request.status,
                # Left unset on purpose: `list_pending_approvals` matches
                # requests whose approver is the caller *or* nobody, and an
                # unrouted queue is the more common state of a real workspace.
                approver_id=None,
            )
        )


async def _add_compliance(
    db: AsyncSession, prose: Prose, clock: Clock, caller_id: str
) -> None:
    training_id = corpus_id("training", shape.TRAINING_NAME)
    db.add(
        MandatoryTraining(
            id=training_id,
            workspace_id=WORKSPACE_ID,
            name=shape.TRAINING_NAME.replace("-", " ").title(),
            applies_to_type="workspace",
            applies_to_ids=[],
            due_days_after_assignment=30,
            is_active=True,
            extra_data={},
            created_by_id=caller_id,
        )
    )
    await db.flush()

    people = {p.slug: p.id for p in shape.PEOPLE}
    for row in shape.TRAININGS:
        db.add(
            TrainingAssignment(
                id=row.id,
                mandatory_training_id=training_id,
                developer_id=people[row.assignee],
                workspace_id=WORKSPACE_ID,
                due_date=clock.days_ahead(row.due_days),
                status=row.status,
                completed_at=clock.days_ago(1) if row.status == "completed" else None,
                waived_by_id=caller_id if row.status == "waived" else None,
                waived_at=clock.days_ago(1) if row.status == "waived" else None,
                extra_data={},
            )
        )


async def _add_crm(db: AsyncSession, prose: Prose, caller_id: str) -> None:
    """Standard objects come from the product's own seeder.

    `CRMRecord.values` is addressed by attribute slug, and the attributes are
    created alongside the object — hand-rolling a `CRMObject` would produce one
    whose records no filter can reach.
    """
    await CRMObjectService(db).seed_standard_objects(WORKSPACE_ID)
    await db.flush()

    company = (
        await db.execute(
            select(CRMObject).where(
                CRMObject.workspace_id == WORKSPACE_ID,
                CRMObject.object_type == shape.CRM_OBJECT_SLUG,
            )
        )
    ).scalar_one_or_none()
    if company is None:
        return

    for record in shape.CRM_RECORDS:
        db.add(
            CRMRecord(
                id=record.id,
                workspace_id=WORKSPACE_ID,
                object_id=company.id,
                values={
                    "name": record.slug.replace("-", " ").title(),
                    "stage": record.stage,
                },
                owner_id=caller_id,
                created_by_id=caller_id,
                is_archived=False,
            )
        )
