"""The facts of the synthetic world, written by hand.

Everything a benchmark question can be *asked about* lives here: statuses,
priorities, slugs, owners, ages, counts. Nothing here is generated, because the
oracle derives each case's expected answer by filtering these structures — if a
model wrote them, the ground truth would move every time it was re-run.

Prose is the other half and is deliberately absent: subjects, bodies, names and
company descriptions are generated once and frozen (`data/`), keyed by the slugs
below. A reworded ticket subject must never change which tickets match "show me
the open bugs".

Three things here are easy to get wrong and expensive to get wrong quietly.

**Time is an offset, not a timestamp.** Rows say `age_days=5`, and the loader
resolves them against one anchor captured once per load. Scattering
`datetime.now()` through a seeder — as `seed_marketing_demo.py:69` does — gives
every row a slightly different clock and makes "created this week" untestable.
Pinning an absolute date instead would rot the other way: a certificate that
expires on a fixed day eventually expires in the past, and the "expiring soon"
case silently stops testing anything. Offsets keep the *meaning* fixed, which is
what the oracle grades.

**Distractors are load-bearing.** `aexy_sd_open_tickets` has no `priority`
argument, so a model asked for high-priority tickets can only be caught out by
the answer. That requires low-priority tickets sitting next to the high ones,
in the same status. Every filter below has rows that only just miss it.

**The desk is invisible without its taxonomy.** `pending_with` and `request_type`
are slugs validated against the workspace's own active rows, and `is_open`
resolves through whichever stakeholder is marked terminal
(`service_desk_service.py:2091-2100`) — with no closed bucket, every ticket reads
as open. So the taxonomy is seeded from a real industry template rather than
invented here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from tests.ai.evalcorpus.ids import corpus_id

# The desk's shape comes from the product's own template catalogue
# (`services/service_desk_industry_templates.py`). Naming it rather than
# restating its slugs means the corpus cannot drift from what `seed_taxonomy`
# will actually insert.
TEMPLATE_SLUG = "software_support"

# Stakeholder slugs this template defines, repeated here only so the consistency
# test can catch a ticket parked in a bucket the template does not have. The
# test asserts the two agree.
STAKEHOLDERS = ("support", "engineering", "customer", "vendor", "sales", "finance", "closed")
CLOSED_STAKEHOLDER = "closed"
REQUEST_TYPES = ("question", "bug", "feature_request", "incident", "access_request")


# ---------------------------------------------------------------------------
# People
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Person:
    slug: str
    role: str  # workspace role — "owner" grants every permission
    function: str | None = None  # department function_key, for desk routing

    @property
    def id(self) -> str:
        return corpus_id("developer", self.slug)

    @property
    def email(self) -> str:
        return f"{self.slug}@aexyeval.example.com"


# `analyst` is the caller every eval case runs as. Owner on purpose: the owner
# role carries every permission (`models/permissions.py:461`), including
# `can_view_all_service_desk`, so `resolve_scope_clause` returns None and the
# desk is fully visible. Without that a caller sees only tickets pending with
# their own department or assigned to them personally, and most of the grid
# below would be invisible for reasons that have nothing to do with the model.
CALLER = Person("analyst", role="owner")

PEOPLE = (
    CALLER,
    Person("dana", role="member", function="engineering"),
    Person("ravi", role="member", function="engineering"),
    Person("mina", role="member", function="support"),
)


# ---------------------------------------------------------------------------
# Service desk
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Account:
    slug: str

    @property
    def id(self) -> str:
        return corpus_id("account", self.slug)


# Two Northwinds on purpose. A model that matches on a prefix, or that asks for
# "the Northwind account", has to disambiguate rather than guess.
ACCOUNTS = (
    Account("northwind-traders"),
    Account("northwind-logistics"),
    Account("contoso-cloud"),
)


@dataclass(frozen=True)
class DeskTicket:
    slug: str
    request_type: str
    pending_with: str
    status: str
    priority: str
    severity: str
    account: str
    age_days: int
    assignee: str | None = None
    needs_triage: bool = False

    @property
    def id(self) -> str:
        return corpus_id("ticket", self.slug)

    @property
    def is_open(self) -> bool:
        return self.pending_with != CLOSED_STAKEHOLDER


# The grid. Read it as a table: every filter a case can apply has rows that
# match and rows that only just miss.
#
# The pairing that matters most is high-priority-and-new against
# low-priority-and-new. Those two questions produce identical tool arguments,
# because the tool cannot filter on priority, so they are the pair that proves
# outcome grading works at all.
TICKETS = (
    DeskTicket("sd-login-outage",     "incident",        "engineering", "in_progress",          "urgent", "critical", "contoso-cloud",       0,  "ravi"),
    DeskTicket("sd-import-crash",     "bug",             "engineering", "new",                  "urgent", "critical", "northwind-traders",   2,  "dana"),
    DeskTicket("sd-export-timeout",   "bug",             "engineering", "in_progress",          "high",   "high",     "northwind-traders",   5,  "dana"),
    DeskTicket("sd-webhook-retry",    "bug",             "support",     "new",                  "high",   "high",     "northwind-logistics", 1,  None, True),
    DeskTicket("sd-sso-access",       "access_request",  "support",     "new",                  "high",   "medium",   "contoso-cloud",       1,  "mina"),
    DeskTicket("sd-vendor-latency",   "bug",             "vendor",      "waiting_on_submitter", "high",   "high",     "northwind-logistics", 12, "ravi"),
    DeskTicket("sd-report-mismatch",  "incident",        "support",     "new",                  "medium", "medium",   "contoso-cloud",       0,  None, True),
    DeskTicket("sd-bulk-edit",        "feature_request", "support",     "new",                  "medium", "medium",   "northwind-logistics", 4,  None, True),
    DeskTicket("sd-dark-mode",        "feature_request", "engineering", "acknowledged",         "medium", "low",      "northwind-traders",   14, "dana"),
    DeskTicket("sd-invoice-query",    "question",        "finance",     "in_progress",          "low",    "low",      "northwind-traders",   7,  "dana"),
    DeskTicket("sd-onboarding-howto", "question",        "support",     "new",                  "low",    "low",      "northwind-traders",   3,  "mina"),
    DeskTicket("sd-timezone-display", "question",        "customer",    "waiting_on_submitter", "low",    "low",      "northwind-logistics", 9,  "mina"),
    # Closed tail. `pending_with="closed"` is what makes `is_open=false` true —
    # the ticket status alone does not, which is a distinction a case can test.
    DeskTicket("sd-payment-outage",   "incident",        "closed",      "closed",               "urgent", "critical", "contoso-cloud",       30, "ravi"),
    DeskTicket("sd-legacy-crash",     "bug",             "closed",      "resolved",             "urgent", "critical", "northwind-logistics", 60, "dana"),
    DeskTicket("sd-billing-question", "question",        "closed",      "resolved",             "medium", "medium",   "contoso-cloud",       21, "mina"),
    DeskTicket("sd-old-vpn-access",   "access_request",  "closed",      "closed",               "low",    "low",      "northwind-traders",   40, "mina"),
)


# ---------------------------------------------------------------------------
# Sprints and tracking
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Sprint:
    slug: str
    status: str
    starts_days_ago: int
    ends_days_ahead: int

    @property
    def id(self) -> str:
        return corpus_id("sprint", self.slug)


# A completed sprint beside the active one, so "the current sprint" is a choice
# rather than the only row in the table.
SPRINTS = (
    Sprint("autumn-hardening", status="active", starts_days_ago=6, ends_days_ahead=8),
    Sprint("summer-cleanup", status="completed", starts_days_ago=34, ends_days_ahead=-20),
)
ACTIVE_SPRINT = SPRINTS[0].slug


@dataclass(frozen=True)
class Task:
    slug: str
    sprint: str
    status: str
    priority: str
    assignee: str | None = None
    story_points: int | None = None

    @property
    def id(self) -> str:
        return corpus_id("task", self.slug)


# Sprint hygiene is a documented use of `aexy_sprint_tasks` ("look for unassigned
# tasks, tasks with no estimate, in-progress tasks that have not moved"), so the
# board carries one of each rather than being uniformly healthy.
TASKS = (
    Task("t-auth-api", ACTIVE_SPRINT, "in_progress", "high", "dana", 5),
    Task("t-rate-limit", ACTIVE_SPRINT, "in_progress", "high", "ravi", 3),
    Task("t-dashboard-load", ACTIVE_SPRINT, "todo", "medium", "mina", 3),
    Task("t-migration-script", ACTIVE_SPRINT, "todo", "medium", None, 2),       # unassigned
    Task("t-flaky-e2e", ACTIVE_SPRINT, "todo", "low", "dana", None),            # no estimate
    Task("t-audit-log", ACTIVE_SPRINT, "done", "medium", "ravi", 5),
    Task("t-legacy-purge", "summer-cleanup", "done", "low", "mina", 2),
    Task("t-config-split", "summer-cleanup", "done", "medium", "dana", 3),
)


@dataclass(frozen=True)
class Blocker:
    slug: str
    status: str  # active | escalated | resolved
    severity: str
    reporter: str
    reported_days_ago: int

    @property
    def id(self) -> str:
        return corpus_id("blocker", self.slug)


# `aexy_active_blockers` counts active and escalated and excludes resolved, and
# that exclusion was itself a past bug (see the 0.8.x changelog), so the resolved
# row is here to keep it honest.
BLOCKERS = (
    Blocker("b-staging-db", status="active", severity="high", reporter="dana", reported_days_ago=2),
    Blocker("b-vendor-api-key", status="escalated", severity="critical", reporter="ravi", reported_days_ago=4),
    Blocker("b-design-signoff", status="resolved", severity="medium", reporter="mina", reported_days_ago=11),
)


# ---------------------------------------------------------------------------
# Expected counts
# ---------------------------------------------------------------------------
#
# Hand-declared, and checked against the tables above by
# `tests/unit/test_eval_corpus_shape.py`. They are not the oracle — the oracle
# filters the rows itself — they are a second opinion, so that editing the grid
# and miscounting fails a test instead of quietly rewriting what the benchmark
# considers a correct answer.


@dataclass(frozen=True)
class ExpectedCounts:
    by_status: dict[str, int] = field(default_factory=dict)
    by_pending_with: dict[str, int] = field(default_factory=dict)
    by_request_type: dict[str, int] = field(default_factory=dict)
    new_by_priority: dict[str, int] = field(default_factory=dict)
    open_tickets: int = 0
    needs_triage: int = 0


EXPECTED = ExpectedCounts(
    by_status={
        "new": 6,
        "in_progress": 3,
        "acknowledged": 1,
        "waiting_on_submitter": 2,
        "resolved": 2,
        "closed": 2,
    },
    by_pending_with={
        "engineering": 4,
        "support": 5,
        "customer": 1,
        "vendor": 1,
        "finance": 1,
        "closed": 4,
    },
    by_request_type={
        "bug": 5,
        "incident": 3,
        "question": 4,
        "feature_request": 2,
        "access_request": 2,
    },
    # The pair that path-only grading cannot tell apart.
    new_by_priority={"urgent": 1, "high": 2, "medium": 2, "low": 1},
    open_tickets=12,
    needs_triage=3,
)


# ---------------------------------------------------------------------------
# Uptime
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Monitor:
    slug: str
    current_status: str  # up | down

    @property
    def id(self) -> str:
        return corpus_id("monitor", self.slug)


@dataclass(frozen=True)
class Incident:
    slug: str
    monitor: str
    status: str  # ongoing | resolved
    started_days_ago: int
    acknowledged: bool = False

    @property
    def id(self) -> str:
        return corpus_id("incident", self.slug)


MONITORS = (
    Monitor("api-gateway", current_status="down"),
    Monitor("checkout-service", current_status="up"),
)

# One ongoing incident that nobody has looked at, one ongoing and acknowledged,
# one resolved. `aexy_open_incidents` filters on status, and the acknowledged
# row is what stops "open" and "unacknowledged" being accidentally the same
# question.
INCIDENTS = (
    Incident("api-gateway-5xx", "api-gateway", status="ongoing", started_days_ago=0),
    Incident("checkout-latency", "checkout-service", status="ongoing",
             started_days_ago=1, acknowledged=True),
    Incident("api-gateway-timeout", "api-gateway", status="resolved", started_days_ago=9),
)


# ---------------------------------------------------------------------------
# Leave
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LeaveRequestRow:
    slug: str
    requester: str
    leave_type: str
    status: str  # pending | approved | rejected
    starts_days_ahead: int
    days: float

    @property
    def id(self) -> str:
        return corpus_id("leave-request", self.slug)


LEAVE_TYPES = ("annual", "sick")

# `aexy_leave_pending_approvals` returns requests with status "pending" whose
# approver is the caller or unset. The approved and rejected rows are here so
# that a tool ignoring the status filter is visibly wrong.
LEAVE_REQUESTS = (
    LeaveRequestRow("dana-annual", "dana", "annual", "pending", starts_days_ahead=14, days=5),
    LeaveRequestRow("ravi-sick", "ravi", "sick", "pending", starts_days_ahead=1, days=2),
    LeaveRequestRow("mina-annual", "mina", "annual", "approved", starts_days_ahead=30, days=3),
    LeaveRequestRow("dana-sick-past", "dana", "sick", "rejected", starts_days_ahead=-10, days=1),
)


# ---------------------------------------------------------------------------
# Compliance
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TrainingRow:
    slug: str
    assignee: str
    status: str  # assigned | in_progress | completed | waived
    due_days: int  # negative is overdue

    @property
    def id(self) -> str:
        return corpus_id("training-assignment", self.slug)

    @property
    def is_overdue(self) -> bool:
        # The report's own rule: past due, and not finished or excused.
        return self.due_days < 0 and self.status not in ("completed", "waived")


TRAINING_NAME = "security-awareness"

# Two genuinely overdue, and three near misses: one overdue but completed, one
# overdue but waived, one still in the future. Without those the report's
# `status NOT IN (completed, waived)` clause is untested and a tool that dropped
# it would score identically.
TRAININGS = (
    TrainingRow("dana-security", "dana", "assigned", due_days=-12),
    TrainingRow("ravi-security", "ravi", "in_progress", due_days=-3),
    TrainingRow("mina-security", "mina", "completed", due_days=-20),
    TrainingRow("analyst-security", "analyst", "waived", due_days=-5),
    TrainingRow("dana-security-next", "dana", "assigned", due_days=21),
)


# ---------------------------------------------------------------------------
# CRM
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CrmRecordRow:
    slug: str
    stage: str

    @property
    def id(self) -> str:
        return corpus_id("crm-record", self.slug)


CRM_OBJECT_SLUG = "company"

CRM_RECORDS = (
    CrmRecordRow("acme-industrial", stage="prospect"),
    CrmRecordRow("acme-logistics", stage="customer"),
    CrmRecordRow("globex-systems", stage="customer"),
)
