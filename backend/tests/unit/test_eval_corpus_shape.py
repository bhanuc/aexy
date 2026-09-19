"""The corpus has to be internally consistent before it can be ground truth.

These are cheap checks, and they exist because the failure they catch is silent.
A ticket parked in a stakeholder bucket the template never creates does not
raise: `pending_with` is a free-text slug, so the row loads, and then every
question about that queue quietly returns nothing. A miscounted grid is worse —
the benchmark keeps running and marks correct answers wrong.

No database and no LLM: this is the shape checking itself.
"""

from __future__ import annotations

from collections import Counter

import pytest

from aexy.services.service_desk_industry_templates import get_template
from tests.ai.evalcorpus import shape
from tests.ai.evalcorpus.ids import corpus_id

# ─── identifiers ───────────────────────────────────────────────────────


def test_ids_are_stable_across_calls():
    assert corpus_id("ticket", "sd-import-crash") == corpus_id("ticket", "sd-import-crash")


def test_ids_are_namespaced_by_kind():
    assert corpus_id("ticket", "shared") != corpus_id("account", "shared")


def test_no_id_group_is_all_digits():
    """SQLite reads an all-digit id back as a float — see `ids._letterise`."""
    rows = [*shape.PEOPLE, *shape.ACCOUNTS, *shape.TICKETS, *shape.SPRINTS, *shape.TASKS, *shape.BLOCKERS]
    offenders = [
        row.id
        for row in rows
        if any(group.isdigit() for group in row.id.split("-"))
    ]
    assert offenders == []


def test_every_row_has_a_distinct_id():
    rows = [*shape.PEOPLE, *shape.ACCOUNTS, *shape.TICKETS, *shape.SPRINTS, *shape.TASKS, *shape.BLOCKERS]
    ids = [row.id for row in rows]
    assert len(set(ids)) == len(ids)


# ─── referential integrity ─────────────────────────────────────────────


def test_the_taxonomy_matches_the_template_the_loader_will_seed():
    """Otherwise a ticket sits in a bucket that does not exist, and vanishes."""
    template = get_template(shape.TEMPLATE_SLUG)
    assert template is not None, shape.TEMPLATE_SLUG
    assert {s.slug for s in template.stakeholders} == set(shape.STAKEHOLDERS)
    assert {r.slug for r in template.request_types} == set(shape.REQUEST_TYPES)


def test_the_closed_stakeholder_is_the_one_the_template_calls_terminal():
    """`is_open` resolves through this, so naming the wrong slug hides nothing."""
    template = get_template(shape.TEMPLATE_SLUG)
    terminal = [s.slug for s in template.stakeholders if s.semantics == "closed"]
    assert terminal == [shape.CLOSED_STAKEHOLDER]


@pytest.mark.parametrize("ticket", shape.TICKETS, ids=lambda t: t.slug)
def test_each_ticket_points_at_rows_that_exist(ticket):
    assert ticket.pending_with in shape.STAKEHOLDERS
    assert ticket.request_type in shape.REQUEST_TYPES
    assert ticket.account in {a.slug for a in shape.ACCOUNTS}
    if ticket.assignee is not None:
        assert ticket.assignee in {p.slug for p in shape.PEOPLE}


@pytest.mark.parametrize("task", shape.TASKS, ids=lambda t: t.slug)
def test_each_task_points_at_rows_that_exist(task):
    assert task.sprint in {s.slug for s in shape.SPRINTS}
    if task.assignee is not None:
        assert task.assignee in {p.slug for p in shape.PEOPLE}


def test_exactly_one_sprint_is_active():
    active = [s.slug for s in shape.SPRINTS if s.status == "active"]
    assert active == [shape.ACTIVE_SPRINT]


def test_the_caller_can_see_the_whole_desk():
    """`resolve_scope_clause` returns None only for a full-view permission."""
    assert shape.CALLER.role == "owner"


# ─── declared counts vs the grid ───────────────────────────────────────


def test_status_counts_match():
    assert Counter(t.status for t in shape.TICKETS) == shape.EXPECTED.by_status


def test_pending_with_counts_match():
    assert Counter(t.pending_with for t in shape.TICKETS) == shape.EXPECTED.by_pending_with


def test_request_type_counts_match():
    assert Counter(t.request_type for t in shape.TICKETS) == shape.EXPECTED.by_request_type


def test_open_ticket_count_matches():
    assert sum(1 for t in shape.TICKETS if t.is_open) == shape.EXPECTED.open_tickets


def test_needs_triage_count_matches():
    assert sum(1 for t in shape.TICKETS if t.needs_triage) == shape.EXPECTED.needs_triage


def test_new_tickets_split_by_priority():
    counts = Counter(t.priority for t in shape.TICKETS if t.status == "new")
    assert counts == shape.EXPECTED.new_by_priority


# ─── the distractors that make grading possible ────────────────────────


def test_high_and_low_priority_new_tickets_both_exist():
    """The `ask_001`/`ask_002` pair.

    Both questions produce the same tool arguments, because
    `aexy_sd_open_tickets` has no `priority` parameter. They are separable only
    by the answer, and only if both sets are non-empty and different.
    """
    new = [t for t in shape.TICKETS if t.status == "new"]
    high = {t.slug for t in new if t.priority == "high"}
    low = {t.slug for t in new if t.priority == "low"}
    assert high and low
    assert high.isdisjoint(low)


def test_every_priority_appears_in_more_than_one_status():
    """A filter that is really a priority filter in disguise would pass otherwise."""
    for priority in ("urgent", "high", "medium", "low"):
        statuses = {t.status for t in shape.TICKETS if t.priority == priority}
        assert len(statuses) > 1, priority


def test_closed_tickets_are_the_ones_in_the_terminal_bucket():
    """`is_open` keys on `pending_with`, not on ticket status."""
    closed = {t.slug for t in shape.TICKETS if not t.is_open}
    terminal = {t.slug for t in shape.TICKETS if t.pending_with == shape.CLOSED_STAKEHOLDER}
    assert closed == terminal


def test_the_board_has_something_to_report_on():
    active = [t for t in shape.TASKS if t.sprint == shape.ACTIVE_SPRINT]
    assert any(t.assignee is None for t in active), "no unassigned task"
    assert any(t.story_points is None for t in active), "no unestimated task"
    assert any(t.status == "in_progress" for t in active)


def test_blockers_cover_the_active_and_excluded_states():
    states = {b.status for b in shape.BLOCKERS}
    assert {"active", "escalated"} <= states
    assert "resolved" in states, "nothing to check the exclusion against"
