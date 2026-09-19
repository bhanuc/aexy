"""The committed cases file, and the properties that make it gradeable.

`--check` is documented for CI and this repo has no CI, so the staleness check
lives here too — the same arrangement `test_app_catalog_fixture.py` uses for the
app catalogue.

The rest are properties no hand-written fixture had. They are worth asserting
because each one, when it was false, silently degraded the benchmark rather than
breaking it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from generate_eval_cases import (
    CASES,
    DEFAULT_OUT,
    TicketFilter,
    build_payload,
    equivalent_tool_sets,
    render,
    ticket_numbers,
)

from tests.ai.evalcorpus import shape


@pytest.fixture(scope="module")
def payload():
    return build_payload()


@pytest.fixture(scope="module")
def cases(payload):
    return payload["cases"]


# ─── staleness ─────────────────────────────────────────────────────────


def test_the_committed_fixture_is_what_the_generator_writes(payload):
    assert DEFAULT_OUT.exists(), f"{DEFAULT_OUT} missing — run the generator"
    assert DEFAULT_OUT.read_text() == render(payload), (
        "aexy_eval_cases.json is stale — re-run "
        "`python scripts/generate_eval_cases.py` and commit."
    )


def test_the_fixture_still_satisfies_the_harness_loader():
    """`load_eval_cases` requires a task_id and a prompt on every case."""
    data = json.loads(DEFAULT_OUT.read_text())
    entries = data["cases"] if isinstance(data, dict) else data
    assert entries
    for entry in entries:
        assert entry["task_id"]
        assert entry["prompt"]


def test_task_ids_are_unique(cases):
    ids = [case["task_id"] for case in cases]
    assert len(set(ids)) == len(ids)


# ─── the defect this replaces ──────────────────────────────────────────


def test_the_high_and_low_priority_cases_are_finally_distinguishable(cases):
    """`ask_001` and `ask_002` declared the same expected arguments.

    They had to: `aexy_sd_open_tickets` takes no `priority`. So the two
    questions were graded identically and the benchmark could not tell a model
    that answered one from a model that answered the other. The arguments are
    still identical — that part was never wrong — but the expected answers now
    differ, which is the only place the difference can live.
    """
    high = next(c for c in cases if c["task_id"] == "sd_new_high")
    low = next(c for c in cases if c["task_id"] == "sd_new_low")

    assert high["expected_arguments"] == low["expected_arguments"]

    assert high["expected_outcome"]["count"] > 0
    assert low["expected_outcome"]["count"] > 0
    assert set(high["expected_outcome"]["ids"]).isdisjoint(low["expected_outcome"]["ids"])


def test_no_case_expects_an_argument_the_tool_does_not_accept():
    """Passing `priority` would score every correct model zero on arguments."""
    accepted = {"needs_triage", "pending_with", "request_type", "status",
                "is_open", "assigned_to", "q", "limit", "offset", "fields"}
    for case in CASES:
        if case.ticket_filter is None:
            continue
        assert set(case.ticket_filter.tool_arguments()) <= accepted, case.task_id


# ─── equivalent paths ──────────────────────────────────────────────────


def test_every_case_accepts_the_generic_call_route(cases):
    """A model answering via `aexy_call` is right, and used to score zero."""
    for case in cases:
        if case["task_id"] == "local_time":
            continue
        flattened = {tool for tool_set in case["acceptable_tool_sets"] for tool in tool_set}
        assert "aexy_call" in flattened, case["task_id"]


def test_the_named_routine_is_offered_first(cases):
    """`select_best_tool_set` breaks ties on order, so the canonical path wins."""
    for case in cases:
        expected_tool = next(iter(case["expected_arguments"]))
        assert expected_tool in case["acceptable_tool_sets"][0], case["task_id"]


def test_a_multi_hop_case_allows_the_lookup_that_precedes_it(cases):
    """`aexy_sprint_tasks` needs a sprint_id nobody asking the question knows."""
    case = next(c for c in cases if c["task_id"] == "sprint_tasks")
    assert ["aexy_sprints", "aexy_sprint_tasks"] in case["acceptable_tool_sets"]
    assert case["max_iterations"] >= 2


def test_a_local_tool_gets_no_catalogue_equivalents():
    assert equivalent_tool_sets("current_time") == [["current_time"]]


# ─── the oracle agrees with the shape ──────────────────────────────────


def test_every_ticket_case_names_rows_that_exist(cases):
    known = {t.id for t in shape.TICKETS}
    for case in cases:
        outcome = case["expected_outcome"]
        if outcome.get("kind") != "tickets":
            continue
        assert set(outcome["ids"]) <= known, case["task_id"]
        assert len(outcome["ids"]) == outcome["count"], case["task_id"]


def test_ticket_numbers_follow_the_order_the_loader_uses(cases):
    """The loader numbers tickets by their position in `shape.TICKETS`.

    A model quotes a ticket by number, so a mismatch here would mark correct
    answers wrong — and would do it quietly.
    """
    numbers = ticket_numbers()
    assert numbers[shape.TICKETS[0].slug] == 1
    assert numbers[shape.TICKETS[-1].slug] == len(shape.TICKETS)


@pytest.mark.parametrize(
    "status,expected", sorted(shape.EXPECTED.by_status.items())
)
def test_the_filter_agrees_with_the_hand_declared_counts(status, expected):
    assert len(TicketFilter(status=status).select()) == expected


def test_a_filter_with_no_criteria_selects_everything():
    assert len(TicketFilter().select()) == len(shape.TICKETS)


def test_the_open_filter_keys_on_the_terminal_bucket():
    selected = TicketFilter(is_open=False).select()
    assert {t.slug for t in selected} == {
        t.slug for t in shape.TICKETS if t.pending_with == shape.CLOSED_STAKEHOLDER
    }
