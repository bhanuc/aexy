"""Outcome grading — the half of the benchmark that reads the answer.

These metrics decide whether a model said the right thing, and they are the only
thing that can separate two questions producing an identical tool call. So they
are tested against text shaped like what a model actually writes, rather than
against tidy inputs.
"""

from __future__ import annotations

import pytest

from tests.ai.utils.eval_metrics import (
    answer_precision,
    answer_recall,
    evaluate_outcome,
    hallucinated_entities,
    outcome_success,
    referenced_numbers,
)

UUID_A = "aaaaaaaa-1111-4aaa-8aaa-aaaaaaaaaaa1"
UUID_B = "bbbbbbbb-2222-4bbb-8bbb-bbbbbbbbbbb2"
UUID_C = "dddddddd-4444-4ddd-8ddd-ddddddddddd4"

HIGH = {"kind": "tickets", "count": 2, "ticket_numbers": [4, 5], "ids": [UUID_A, UUID_B]}
LOW = {"kind": "tickets", "count": 1, "ticket_numbers": [11], "ids": [UUID_C]}
UNIVERSE = {"ticket_numbers": list(range(1, 17)), "ids": [UUID_A, UUID_B, UUID_C]}


# ─── how a reference is recognised ─────────────────────────────────────


@pytest.mark.parametrize(
    "text,expected",
    [
        ("See #4 for details.", {4}),
        ("Tickets #4 and #5 are urgent.", {4, 5}),
        ("Ticket 11 is the low-priority one.", {11}),
        ("Ticket #004 is zero padded.", {4}),
        ("# 7 has a space.", {7}),
    ],
)
def test_the_ways_a_model_writes_a_ticket_reference(text, expected):
    assert referenced_numbers(text) == expected


def test_a_count_is_not_a_reference():
    """"There are 2 tickets" must not score as naming ticket #2.

    Matching bare numbers would manufacture recall out of any answer that
    summarised itself, which is every answer.
    """
    assert referenced_numbers("There are 2 tickets, and 3 were closed.") == set()


# ─── recall ────────────────────────────────────────────────────────────


def test_naming_every_expected_row_is_full_recall():
    assert answer_recall(HIGH, "The high-priority ones are #4 and #5.") == 1.0


def test_naming_none_of_them_is_zero():
    assert answer_recall(HIGH, "There are two high-priority tickets.") == 0.0


def test_naming_half_of_them_is_half():
    assert answer_recall(HIGH, "Only #4 is high priority.") == 0.5


def test_a_uuid_counts_when_a_model_echoes_the_tool_result():
    assert answer_recall(LOW, f"The ticket is {UUID_C}.") == 1.0


def test_a_case_expecting_nothing_is_not_a_miss():
    """`current_time` names no rows; scoring it zero would be nonsense."""
    assert answer_recall({"kind": "none", "count": 0, "ids": []}, "It is 14:05 UTC.") == 1.0


# ─── precision ─────────────────────────────────────────────────────────


def test_listing_extra_rows_costs_precision():
    """Asked for the two high-priority tickets, a model that lists all six new
    ones has named both — full recall, wrong answer. Precision is what catches
    it, and why outcome success needs more than recall."""
    assert answer_recall(HIGH, "New tickets: #2, #4, #5, #7, #8, #11.") == 1.0
    assert answer_precision(HIGH, "New tickets: #2, #4, #5, #7, #8, #11.", UNIVERSE) < 1.0


def test_naming_exactly_the_right_rows_is_full_precision():
    assert answer_precision(HIGH, "#4 and #5.", UNIVERSE) == 1.0


def test_an_answer_naming_nothing_has_no_precision():
    assert answer_precision(HIGH, "I could not find any.", UNIVERSE) == 0.0


def test_an_invented_reference_is_not_counted_against_precision():
    """It is a hallucination, reported separately — a different, worse failure."""
    assert answer_precision(HIGH, "#4, #5 and #42.", UNIVERSE) == 1.0
    assert hallucinated_entities("#4, #5 and #42.", UNIVERSE) == ["#42"]


# ─── hallucination ─────────────────────────────────────────────────────


def test_a_ticket_that_does_not_exist_is_flagged():
    assert hallucinated_entities("Ticket #99 is overdue.", UNIVERSE) == ["#99"]


def test_an_invented_uuid_is_flagged():
    invented = "cccccccc-3333-4ccc-8ccc-ccccccccccc3"
    assert hallucinated_entities(f"See {invented}.", UNIVERSE) == [invented]


def test_real_references_are_not_flagged():
    assert hallucinated_entities(f"#4, #16 and {UUID_B}.", UNIVERSE) == []


def test_without_a_universe_nothing_is_called_invented():
    """A hand-written fixture carries no universe; guessing would be worse."""
    assert hallucinated_entities("Ticket #9999.", None) == []


# ─── success ───────────────────────────────────────────────────────────


def test_the_whole_answer_and_nothing_else_succeeds():
    assert outcome_success(HIGH, "The high-priority new tickets are #4 and #5.", UNIVERSE)


def test_a_partial_answer_fails():
    assert not outcome_success(HIGH, "#4 is high priority.", UNIVERSE)


def test_an_over_inclusive_answer_fails():
    assert not outcome_success(HIGH, "#2, #4, #5, #7, #8 and #11.", UNIVERSE)


def test_a_complete_answer_with_an_invention_fails():
    assert not outcome_success(HIGH, "#4, #5, and also #42.", UNIVERSE)


# ─── the pair that path grading cannot separate ────────────────────────


def test_the_same_call_with_two_different_answers_grades_differently():
    """The defect this whole phase exists to fix.

    `sd_new_high` and `sd_new_low` issue an identical call, because the tool has
    no `priority` argument. Under path-only grading both answers below scored
    the same. They must not.
    """
    high_answer = "The high-priority new tickets are #4 and #5."
    low_answer = "The low-priority new ticket is #11."

    assert outcome_success(HIGH, high_answer, UNIVERSE)
    assert not outcome_success(HIGH, low_answer, UNIVERSE)

    assert outcome_success(LOW, low_answer, UNIVERSE)
    assert not outcome_success(LOW, high_answer, UNIVERSE)


# ─── the shape the harness consumes ────────────────────────────────────


def test_evaluate_outcome_reports_every_metric():
    result = evaluate_outcome(
        case={"expected_outcome": HIGH},
        response="#4 and #5, plus a made-up #42.",
        universe=UNIVERSE,
    )
    assert result["expected_count"] == 2
    assert result["answer_recall"] == 1.0
    assert result["answer_precision"] == 1.0
    assert result["hallucinated_entities"] == ["#42"]
    assert result["outcome_success"] is False


def test_a_case_with_no_expected_outcome_does_not_crash():
    """A hand-written case predating the generator has no outcome block."""
    result = evaluate_outcome(case={}, response="anything", universe=None)
    assert result["answer_recall"] == 1.0
    assert result["outcome_success"] is True


# ─── titles, the anchor a model actually uses ──────────────────────────

TITLED = {
    "kind": "tickets",
    "count": 2,
    "ticket_numbers": [4, 5],
    "ids": [UUID_A, UUID_B],
    "titles": [
        "Webhook deliveries are not retried after a failure",
        "Need SSO access for new team members",
    ],
}


def test_an_answer_that_quotes_titles_and_no_numbers_still_scores():
    """The common case, and the one numbers alone could not grade.

    Models summarise in prose: they name the ticket, not its id, and often not
    its number either. Before titles existed as an anchor this answer scored
    zero recall while being completely correct.
    """
    response = (
        "Two of the new tickets are high priority: Webhook deliveries are not "
        "retried after a failure, and Need SSO access for new team members."
    )
    assert answer_recall(TITLED, response) == 1.0


def test_title_matching_ignores_case():
    assert answer_recall(TITLED, "webhook deliveries are NOT retried after a failure") == 0.5


def test_any_one_anchor_is_enough_for_a_row():
    """Number, id or title — a row named any way it can be named counts once."""
    assert answer_recall(TITLED, f"#4 and {UUID_B}") == 1.0


def test_a_row_named_twice_is_still_one_row():
    response = f"#4 — Webhook deliveries are not retried after a failure ({UUID_A})"
    assert answer_recall(TITLED, response) == 0.5


def test_titles_are_optional():
    """Cases generated before the corpus text existed carry no titles."""
    assert answer_recall(HIGH, "#4 and #5.") == 1.0
