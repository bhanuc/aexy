"""Derive the benchmark's cases from the corpus, so the answers are computed.

The five hand-written cases this replaces had a defect that could not be fixed by
writing them more carefully. `ask_001` asked for high-priority tickets and
`ask_002` for low-priority, and both declared the same expected arguments —
necessarily, because `aexy_sd_open_tickets` has no `priority` parameter
(`mcp_catalog.py:755-770`). Two opposite questions, one expected call. Nothing
downstream could tell a right answer from a wrong one.

A case here is a prompt plus a *filter*. The filter is applied to
`tests/ai/evalcorpus/shape.py` to work out which rows answer the question, and
that produces three things at once: the arguments the tool should be called with,
the tool sets that count as reaching the answer, and — new — the rows the answer
must actually name. The high/low pair now differs in the third, which is the only
place it ever could.

**Equivalent paths are enumerated.** `path_success` demands an F1 of 1.0 against
one entry in `acceptable_tool_sets`, and alongside the named routines a model is
offered `aexy_discover`, `aexy_call` and a tool per capability. A model that
answers correctly through `aexy_call {"action": "list_tickets"}` was scoring
zero. Every case now lists the generic and per-capability routes beside the
named one.

**Generated and committed**, in the shape of `dump_app_catalog.py` and
`dump_mcp_catalog.py`: a pure `build_payload()`, `--out <path|->`, and `--check`
that fails when the committed file no longer matches. `tests/unit/
test_eval_cases_fixture.py` imports `build_payload` and asserts the same thing,
because `--check` is documented for CI and this repo has no CI.

    python scripts/generate_eval_cases.py            # write the fixture
    python scripts/generate_eval_cases.py --check    # is it stale?
    python scripts/generate_eval_cases.py --out -    # to stdout
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent))

from aexy.services.mcp_catalog import WORKFLOW_TOOLS
from tests.ai.evalcorpus import shape
from tests.ai.evalcorpus.load import PROSE_FILE, Prose

DEFAULT_OUT = (
    Path(__file__).parent.parent / "tests" / "ai" / "fixtures" / "aexy_eval_cases.json"
)

# Tools the application answers locally rather than through the catalogue, so
# they have no capability and no generic equivalent.
LOCAL_TOOLS = {"current_time"}

_CAPABILITY_OF = {tool["name"]: tool["capability"] for tool in WORKFLOW_TOOLS}


def equivalent_tool_sets(tool: str, *, multi_hop: bool = False) -> list[list[str]]:
    """Every tool set that reaches the same answer, best-known first.

    A capability is `mcp.<app>` and its tool is `aexy_<app>`; `aexy_call` reaches
    any operation the caller holds. Both are offered to the model, so both are
    correct ways to answer and neither should score zero.
    """
    if tool in LOCAL_TOOLS:
        return [[tool]]
    sets = [[tool]]
    capability = _CAPABILITY_OF.get(tool)
    if capability:
        sets.append([f"aexy_{capability.split('.', 1)[1]}"])
    sets.append(["aexy_call"])
    if multi_hop and capability:
        # The model has to look something up before it can make the call. Any
        # of these reaches the answer; excluding them would score a correct
        # two-step answer as a total miss.
        family = f"aexy_{capability.split('.', 1)[1]}"
        sets = [
            [family, tool],
            ["aexy_call", tool],
            ["aexy_discover", tool],
            *sets,
        ]
    return sets


# ---------------------------------------------------------------------------
# The oracle
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TicketFilter:
    """Declarative so it can be tested, and so a case can say what it meant.

    Note that `priority` is a filter the *oracle* can apply and the *tool*
    cannot. That asymmetry is the whole reason outcome grading exists.
    """

    status: str | None = None
    priority: str | None = None
    request_type: str | None = None
    pending_with: str | None = None
    is_open: bool | None = None
    needs_triage: bool | None = None

    # Every field is compared the same way, against the attribute of the same
    # name, so adding a criterion means adding a field and nothing else.
    _CRITERIA = ("status", "priority", "request_type", "pending_with", "is_open", "needs_triage")

    def matches(self, ticket: shape.DeskTicket) -> bool:
        return all(
            getattr(self, name) is None or getattr(ticket, name) == getattr(self, name)
            for name in self._CRITERIA
        )

    def select(self) -> list[shape.DeskTicket]:
        return [t for t in shape.TICKETS if self.matches(t)]

    def tool_arguments(self) -> dict[str, Any]:
        """The subset the tool can actually be asked for.

        `priority` is dropped on purpose — passing an argument the schema does
        not define would make every model that behaves correctly score zero on
        argument accuracy.
        """
        arguments: dict[str, Any] = {}
        if self.status is not None:
            arguments["status"] = self.status
        if self.request_type is not None:
            arguments["request_type"] = self.request_type
        if self.pending_with is not None:
            arguments["pending_with"] = self.pending_with
        if self.is_open is not None:
            arguments["is_open"] = self.is_open
        if self.needs_triage is not None:
            arguments["needs_triage"] = self.needs_triage
        return arguments


def _prose() -> Prose | None:
    """The committed corpus text, if it has been generated.

    Titles are the strongest anchor an answer can be checked against — a model
    writes "Import crashes when uploading a large CSV", not a uuid, and often
    not a number either. They are optional because the cases must still be
    generatable before anyone has run `generate_eval_corpus.py`; the fixture is
    simply weaker without them, and `_meta` records which it is.
    """
    return Prose.from_file() if PROSE_FILE.exists() else None


def ticket_titles() -> dict[str, str]:
    prose = _prose()
    if prose is None:
        return {}
    return {t.slug: prose.get("tickets", t.slug, "subject") for t in shape.TICKETS}


def ticket_numbers() -> dict[str, int]:
    """Ticket numbers, assigned the way the loader assigns them.

    A model quotes a ticket by its number far more often than by its uuid, so
    this is the anchor an answer is most likely to be checkable against.
    """
    return {ticket.slug: number for number, ticket in enumerate(shape.TICKETS, start=1)}


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Case:
    task_id: str
    domain: str
    prompt: str
    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)
    ticket_filter: TicketFilter | None = None
    outcome: Callable[[], dict[str, Any]] | None = None
    max_iterations: int = 2
    multi_hop: bool = False


def _ticket_outcome(ticket_filter: TicketFilter) -> dict[str, Any]:
    numbers = ticket_numbers()
    rows = ticket_filter.select()
    # All three lists are in corpus row order, and a grader zips numbers with
    # ids to count entities — so they must line up. Sorting them independently
    # pairs one ticket's number with another's id, which silently miscounts
    # recall instead of failing.
    titles = ticket_titles()
    outcome = {
        "kind": "tickets",
        "count": len(rows),
        "slugs": [t.slug for t in rows],
        "ticket_numbers": [numbers[t.slug] for t in rows],
        "ids": [t.id for t in rows],
    }
    if titles:
        outcome["titles"] = [titles[t.slug] for t in rows]
    return outcome


def _task_outcome(predicate: Callable[[shape.Task], bool]) -> dict[str, Any]:
    rows = [t for t in shape.TASKS if t.sprint == shape.ACTIVE_SPRINT and predicate(t)]
    return {
        "kind": "sprint_tasks",
        "count": len(rows),
        "slugs": [t.slug for t in rows],
        "ids": [t.id for t in rows],
    }


def _incident_outcome() -> dict[str, Any]:
    rows = [i for i in shape.INCIDENTS if i.status == "ongoing"]
    return {"kind": "incidents", "count": len(rows),
            "slugs": [i.slug for i in rows], "ids": [i.id for i in rows]}


def _leave_outcome() -> dict[str, Any]:
    rows = [r for r in shape.LEAVE_REQUESTS if r.status == "pending"]
    return {"kind": "leave_requests", "count": len(rows),
            "slugs": [r.slug for r in rows], "ids": [r.id for r in rows]}


def _crm_outcome() -> dict[str, Any]:
    rows = list(shape.CRM_RECORDS)
    return {"kind": "crm_records", "count": len(rows),
            "slugs": [r.slug for r in rows], "ids": [r.id for r in rows]}


def _blocker_outcome() -> dict[str, Any]:
    rows = [b for b in shape.BLOCKERS if b.status in ("active", "escalated")]
    return {
        "kind": "blockers",
        "count": len(rows),
        "slugs": [b.slug for b in rows],
        "ids": [b.id for b in rows],
    }


DESK = "aexy_sd_open_tickets"

CASES: tuple[Case, ...] = (
    Case("sd_new", "service_desk", "Show me the new tickets on the service desk.",
         DESK, ticket_filter=TicketFilter(status="new")),
    # The pair. Identical arguments, different answers — and before outcome
    # grading existed, indistinguishable.
    Case("sd_new_high", "service_desk",
         "Which of the new service desk tickets are high priority?",
         DESK, ticket_filter=TicketFilter(status="new", priority="high")),
    Case("sd_new_low", "service_desk",
         "Which of the new service desk tickets are low priority?",
         DESK, ticket_filter=TicketFilter(status="new", priority="low")),
    Case("sd_open", "service_desk", "What is still open on the service desk?",
         DESK, ticket_filter=TicketFilter(is_open=True)),
    Case("sd_closed", "service_desk", "Show me the closed service desk tickets.",
         DESK, ticket_filter=TicketFilter(is_open=False)),
    Case("sd_needs_triage", "service_desk",
         "Which service desk tickets still need triage?",
         DESK, ticket_filter=TicketFilter(needs_triage=True)),
    Case("sd_queue_engineering", "service_desk",
         "What is sitting with the engineering queue?",
         DESK, ticket_filter=TicketFilter(pending_with="engineering")),
    Case("sd_bugs", "service_desk", "List the bug reports on the service desk.",
         DESK, ticket_filter=TicketFilter(request_type="bug")),
    Case("sd_open_incidents", "service_desk",
         "Are there any incidents still open on the service desk?",
         DESK, ticket_filter=TicketFilter(request_type="incident", is_open=True)),
    # Multi-hop: `aexy_sprint_tasks` requires a `sprint_id`, and nobody asking
    # this question knows one. The model has to find the active sprint first,
    # so the discovery step is part of a correct path rather than noise, and
    # `$corpus` lets the harness fill in the id it actually loaded.
    Case("sprint_tasks", "sprints", "What is in the current sprint?",
         "aexy_sprint_tasks",
         arguments={"sprint_id": {"$corpus": f"sprints.{shape.ACTIVE_SPRINT}"}},
         outcome=lambda: _task_outcome(lambda t: True),
         multi_hop=True, max_iterations=3),
    Case("sprint_unassigned", "sprints",
         "Which tasks in the current sprint have nobody assigned?",
         "aexy_sprint_tasks",
         arguments={"sprint_id": {"$corpus": f"sprints.{shape.ACTIVE_SPRINT}"}},
         outcome=lambda: _task_outcome(lambda t: t.assignee is None),
         multi_hop=True, max_iterations=3),
    Case("tracking_blockers", "tracking", "What is blocking the team right now?",
         "aexy_active_blockers", outcome=_blocker_outcome),
    Case("uptime_open_incidents", "uptime",
         "Are there any uptime incidents happening right now?",
         "aexy_open_incidents", arguments={"status": "ongoing"},
         outcome=_incident_outcome),
    Case("leave_pending", "leave",
         "Which leave requests are waiting for my approval?",
         "aexy_leave_pending_approvals", outcome=_leave_outcome),
    # `aexy_crm_records` takes an `object_id`, which the asker does not know —
    # the same multi-hop shape as the sprint cases.
    Case("crm_companies", "crm", "List the companies in the CRM.",
         "aexy_crm_records",
         arguments={"object_id": {"$corpus": "crm_object_id"}},
         outcome=_crm_outcome, multi_hop=True, max_iterations=3),
    Case("local_time", "local", "What is the current time?", "current_time",
         outcome=lambda: {"kind": "none", "count": 0, "slugs": [], "ids": []},
         max_iterations=1),
)


def build_payload() -> dict[str, Any]:
    """The fixture — pure, so a test can recompute it and compare.

    An object rather than a bare array, so the provenance block is not a
    case-shaped entry that every consumer has to learn to skip. `load_eval_cases`
    accepts both.
    """
    cases: list[dict[str, Any]] = []

    for case in CASES:
        if case.ticket_filter is not None:
            arguments = case.ticket_filter.tool_arguments()
            outcome = _ticket_outcome(case.ticket_filter)
        else:
            arguments = dict(case.arguments)
            outcome = case.outcome() if case.outcome else {}

        cases.append(
            {
                "task_id": case.task_id,
                "feature": "ask_ai",
                "domain": case.domain,
                "prompt": case.prompt,
                "acceptable_tool_sets": equivalent_tool_sets(case.tool, multi_hop=case.multi_hop),
                "expected_arguments": {case.tool: arguments},
                "expected_outcome": outcome,
                "forbidden_actions": [],
                "grading_mode": "both",
                "max_iterations": case.max_iterations,
            }
        )

    numbers = ticket_numbers()
    return {
        "_meta": {
            "generator": "scripts/generate_eval_cases.py",
            "source": "tests/ai/evalcorpus/shape.py",
            # Everything the corpus contains, so a grader can tell an answer
            # that names the wrong ticket from one that names a ticket which
            # does not exist. Those are different failures and the second is
            # worse.
            "universe": {
                "ticket_numbers": sorted(numbers.values()),
                "ids": sorted(
                    [t.id for t in shape.TICKETS]
                    + [t.id for t in shape.TASKS]
                    + [b.id for b in shape.BLOCKERS]
                ),
            },
            "note": (
                "Generated. Expected answers are derived by filtering the corpus, "
                "not written by hand — edit shape.py or the CASES table in the "
                "generator and re-run it."
            ),
        },
        "cases": cases,
    }


def render(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="'-' for stdout")
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero if the committed fixture is not what this would write",
    )
    args = parser.parse_args()

    rendered = render(build_payload())

    if args.check:
        path = DEFAULT_OUT if args.out == "-" else Path(args.out)
        if not path.exists():
            print(f"{path} does not exist — run this script and commit.", file=sys.stderr)
            return 1
        if path.read_text() != rendered:
            print(
                f"{path} is stale — re-run `python scripts/generate_eval_cases.py` "
                f"and commit.",
                file=sys.stderr,
            )
            return 1
        print(f"{path} is current.", file=sys.stderr)
        return 0

    if args.out == "-":
        sys.stdout.write(rendered)
    else:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rendered)
        print(f"Wrote {out} ({len(CASES)} cases)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
