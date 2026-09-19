"""
Evaluation metrics for AexyEval.

This module evaluates:
- tool selection
- multiple acceptable tool paths
- argument correctness
- forbidden tool usage
- path success

Aexy tool-call structure:

{
    "id": ...,
    "tool_name": ...,
    "tool_input": ...,
    "tool_result": ...,
    "status": ...
}
"""

from __future__ import annotations

import re
from typing import Any


def _normalize_tools(tools: list[str]) -> list[str]:
    """
    Normalize tool names.
    """
    return [str(tool).strip() for tool in tools]


def select_best_tool_set(
    acceptable_tool_sets: list[list[str]],
    actual_tools: list[str],
) -> list[str]:
    """
    Select the acceptable tool set that best matches the actual tools.

    The best set is selected using the highest tool F1 score.
    """

    if not acceptable_tool_sets:
        return []

    best_set: list[str] = []
    best_score = -1.0

    for expected_tools in acceptable_tool_sets:
        score = tool_f1(
            expected_tools=expected_tools,
            actual_tools=actual_tools,
        )

        if score > best_score:
            best_score = score
            best_set = expected_tools

    return best_set


def tool_precision(
    expected_tools: list[str],
    actual_tools: list[str],
) -> float:
    """
    Calculate tool-selection precision.

    Precision =
        correctly selected tools / all selected tools
    """

    expected = set(_normalize_tools(expected_tools))
    actual = set(_normalize_tools(actual_tools))

    if not actual:
        return 1.0 if not expected else 0.0

    correct = len(expected.intersection(actual))

    return correct / len(actual)


def tool_recall(
    expected_tools: list[str],
    actual_tools: list[str],
) -> float:
    """
    Calculate tool-selection recall.

    Recall =
        correctly selected tools / expected tools
    """

    expected = set(_normalize_tools(expected_tools))
    actual = set(_normalize_tools(actual_tools))

    if not expected:
        return 1.0

    correct = len(expected.intersection(actual))

    return correct / len(expected)


def tool_f1(
    expected_tools: list[str],
    actual_tools: list[str],
) -> float:
    """
    Calculate F1 score for tool selection.
    """

    precision = tool_precision(
        expected_tools=expected_tools,
        actual_tools=actual_tools,
    )

    recall = tool_recall(
        expected_tools=expected_tools,
        actual_tools=actual_tools,
    )

    if precision + recall == 0:
        return 0.0

    return 2 * precision * recall / (precision + recall)


def argument_accuracy(
    expected_arguments: dict[str, dict[str, Any]],
    actual_tool_calls: list[dict[str, Any]],
) -> float:
    """
    Calculate argument-level accuracy using Aexy's actual
    tool-call structure.

    Expected benchmark format:

        {
            "list_tickets": {
                "status": "new",
                "priority": "high"
            }
        }

    Actual Aexy tool call:

        {
            "id": "...",
            "tool_name": "list_tickets",
            "tool_input": {
                "status": "new",
                "priority": "high"
            },
            "tool_result": ...,
            "status": "success"
        }

    Only expected arguments are graded.
    Extra arguments do not automatically reduce accuracy.
    """

    total_arguments = 0
    correct_arguments = 0

    for tool_name, expected_args in expected_arguments.items():

        matching_calls = [
            call
            for call in actual_tool_calls
            if call.get("tool_name") == tool_name
        ]

        matching_call = matching_calls[-1] if matching_calls else None

        if matching_call is None:
            total_arguments += len(expected_args)
            continue

        actual_args = matching_call.get("tool_input", {})

        if actual_args is None:
            actual_args = {}

        for key, expected_value in expected_args.items():
            total_arguments += 1

            if (
                key in actual_args
                and actual_args[key] == expected_value
            ):
                correct_arguments += 1

    if total_arguments == 0:
        return 1.0

    return correct_arguments / total_arguments


def forbidden_tool_rate(
    forbidden_actions: list[str],
    actual_tools: list[str],
) -> float:
    """
    Calculate the proportion of executed tools that were forbidden.

    0.0 means no forbidden tool was used.
    """

    if not actual_tools:
        return 0.0

    forbidden = set(_normalize_tools(forbidden_actions))
    actual = _normalize_tools(actual_tools)

    forbidden_count = sum(
        1
        for tool in actual
        if tool in forbidden
    )

    return forbidden_count / len(actual)


def has_forbidden_action(
    forbidden_actions: list[str],
    actual_tools: list[str],
) -> bool:
    """
    Check whether any forbidden tool/action was used.
    """

    forbidden = set(_normalize_tools(forbidden_actions))
    actual = set(_normalize_tools(actual_tools))

    return bool(forbidden.intersection(actual))


def failed_tool_rate(
    actual_tool_calls: list[dict[str, Any]],
) -> float:
    """
    Calculate the proportion of tool calls whose execution status
    was not successful.

    This uses Aexy's recorded `status` field.
    """

    if not actual_tool_calls:
        return 0.0

    failed = sum(
        1
        for call in actual_tool_calls
        if str(call.get("status", "")).lower()
        not in {"success", "ok"}
    )

    return failed / len(actual_tool_calls)


def all_tools_successful(
    actual_tool_calls: list[dict[str, Any]],
) -> bool:
    """
    Return True if all recorded tool calls completed successfully.
    """

    return failed_tool_rate(actual_tool_calls) == 0.0


def path_success(
    selection_score: float,
    args_score: float,
    forbidden_rate: float,
    failure_rate: float,
    minimum_argument_accuracy: float = 1.0,
) -> bool:
    """
    Determine whether the model followed an acceptable execution path.

    Path success requires:

    1. tool selection score is perfect
    2. argument accuracy satisfies threshold
    3. no forbidden tool/action was used
    4. all tool executions succeeded
    """


    return (
        selection_score == 1.0
        and args_score >= minimum_argument_accuracy
        and forbidden_rate == 0.0
        and failure_rate == 0.0
    )

def evaluate_tool_calls(
    case: dict[str, Any],
    actual_tool_calls: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Evaluate tool calls for one AexyEval case.

    Returns deterministic metrics used by the benchmark runner.
    """

    acceptable_tool_sets = case.get(
        "acceptable_tool_sets",
        [],
    )

    expected_arguments = case.get(
        "expected_arguments",
        {},
    )

    max_iterations=case.get("max_iterations")

    forbidden_actions = case.get(
        "forbidden_actions",
        [],
    )

    actual_tools = [
        call.get("tool_name")
        for call in actual_tool_calls
        if call.get("tool_name")
    ]

    iterations_exceeded = (
    max_iterations is not None
    and len(actual_tool_calls) > max_iterations
    )

    best_expected_set = select_best_tool_set(
        acceptable_tool_sets=acceptable_tool_sets,
        actual_tools=actual_tools,
    )

    precision = tool_precision(
        expected_tools=best_expected_set,
        actual_tools=actual_tools,
    )

    recall = tool_recall(
        expected_tools=best_expected_set,
        actual_tools=actual_tools,
    )

    f1 = tool_f1(
        expected_tools=best_expected_set,
        actual_tools=actual_tools,
    )

    args_accuracy = argument_accuracy(
        expected_arguments=expected_arguments,
        actual_tool_calls=actual_tool_calls,
    )

    forbidden_rate = forbidden_tool_rate(
        forbidden_actions=forbidden_actions,
        actual_tools=actual_tools,
    )

    failure_rate = failed_tool_rate(
        actual_tool_calls=actual_tool_calls,
    )

    successful_path = path_success(
        selection_score=f1,
        args_score=args_accuracy,
        forbidden_rate=forbidden_rate,
        failure_rate=failure_rate,
    )

    return {
        "actual_tools": actual_tools,
        "best_expected_tool_set": best_expected_set,

        "tool_precision": precision,
        "tool_recall": recall,
        "tool_f1": f1,

        "argument_accuracy": args_accuracy,

        "forbidden_tool_rate": forbidden_rate,
        "failed_tool_rate": failure_rate,

        "all_tools_successful": (
            failure_rate == 0.0
        ),

        "iterations_exceeded": iterations_exceeded,

        "path_success": successful_path,
    }

# ===========================================================================
# OUTCOME METRICS
# ===========================================================================
#
# Tool metrics answer "did it make the right call". These answer "did it say
# the right thing", which for a class of questions is the only thing that can
# be answered at all: `aexy_sd_open_tickets` has no `priority` argument, so
# "which new tickets are high priority" and "which are low priority" produce an
# identical call. Path grading scores them the same however the model answers.
#
# The anchors are the ticket numbers and ids a generated case derives from the
# corpus. Numbers are what a model actually writes — it quotes "#4", not a uuid
# — so they carry most of the weight, with ids accepted when a model echoes the
# tool result verbatim. Titles are the strongest anchor of the three and are not
# here yet: they come from the generated corpus text.

# `#4`, `# 4`, `#004`, `ticket 4`, `Ticket #4`. Deliberately not a bare number:
# "there are 2 tickets" is a count, not a reference, and matching it would
# manufacture recall out of any answer that summarised itself.
_TICKET_REFERENCE = re.compile(r"(?:#|\bticket\s+#?)\s*0*(\d+)\b", re.IGNORECASE)
_UUID_REFERENCE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE)


def referenced_numbers(response: str) -> set[int]:
    """Every `#N` the answer mentions."""
    return {int(match) for match in _TICKET_REFERENCE.findall(response or "")}


def referenced_ids(response: str) -> set[str]:
    return {match.lower() for match in _UUID_REFERENCE.findall(response or "")}


def _expected_anchors(
    expected_outcome: dict[str, Any],
) -> list[tuple[int | None, str | None, str | None]]:
    """One (number, id, title) triple per row the answer is supposed to name.

    The lists are emitted in corpus row order by the generator precisely so they
    can be zipped here. Titles carry the most weight in practice: a model writes
    "Webhook deliveries are not retried after a failure", sometimes a number,
    and almost never a uuid.
    """
    numbers = expected_outcome.get("ticket_numbers") or []
    ids = expected_outcome.get("ids") or []
    titles = expected_outcome.get("titles") or []
    length = max(len(numbers), len(ids), len(titles))

    def at(values: list, index: int):
        return values[index] if index < len(values) else None

    return [(at(numbers, i), at(ids, i), at(titles, i)) for i in range(length)]


def answer_recall(
    expected_outcome: dict[str, Any],
    response: str,
) -> float:
    """How much of the correct answer the model actually said.

    1.0 when the case expects nothing, so a question with no rows to name is
    not scored as a miss.
    """
    anchors = _expected_anchors(expected_outcome)
    if not anchors:
        return 1.0

    numbers = referenced_numbers(response)
    ids = referenced_ids(response)

    lowered = (response or "").lower()
    found = sum(
        1
        for number, entity_id, title in anchors
        if (number is not None and number in numbers)
        or (entity_id is not None and entity_id.lower() in ids)
        or (title is not None and title.lower() in lowered)
    )
    return found / len(anchors)


def answer_precision(
    expected_outcome: dict[str, Any],
    response: str,
    universe: dict[str, Any] | None = None,
) -> float:
    """Of the rows the answer named, how many belonged in it.

    Recall alone is not enough. Asked for the two high-priority tickets, a model
    that lists all six new ones has named both of them and would score a perfect
    recall while being wrong. Only references the corpus recognises are counted,
    so an invented number is a hallucination rather than a precision miss — the
    two are different failures and are reported separately.
    """
    anchors = _expected_anchors(expected_outcome)
    if not anchors:
        return 1.0

    known_numbers = set((universe or {}).get("ticket_numbers") or [])
    known_ids = {i.lower() for i in (universe or {}).get("ids") or []}

    said_numbers = referenced_numbers(response) & known_numbers if known_numbers else referenced_numbers(response)
    said_ids = referenced_ids(response) & known_ids if known_ids else referenced_ids(response)
    if not said_numbers and not said_ids:
        return 0.0

    expected_numbers = {n for n, _, _ in anchors if n is not None}
    expected_ids = {i.lower() for _, i, _ in anchors if i is not None}

    said = {("n", n) for n in said_numbers} | {("i", i) for i in said_ids}
    correct = {("n", n) for n in said_numbers & expected_numbers} | {
        ("i", i) for i in said_ids & expected_ids
    }
    return len(correct) / len(said)


def hallucinated_entities(
    response: str,
    universe: dict[str, Any] | None = None,
) -> list[str]:
    """References in the answer that exist nowhere in the corpus.

    A model naming ticket #42 in a workspace with sixteen tickets has invented
    it, which is a different and worse failure than naming the wrong real one.
    Without a universe to check against nothing can be called invented, so the
    answer is an empty list rather than a guess.
    """
    if not universe:
        return []

    known_numbers = set(universe.get("ticket_numbers") or [])
    known_ids = {i.lower() for i in (universe.get("ids") or [])}

    invented = [f"#{n}" for n in sorted(referenced_numbers(response) - known_numbers)]
    invented += sorted(referenced_ids(response) - known_ids)
    return invented


def outcome_success(
    expected_outcome: dict[str, Any],
    response: str,
    universe: dict[str, Any] | None = None,
) -> bool:
    """The whole correct answer, nothing that does not belong, nothing invented."""
    return (
        answer_recall(expected_outcome, response) == 1.0
        and answer_precision(expected_outcome, response, universe) == 1.0
        and not hallucinated_entities(response, universe)
    )


def evaluate_outcome(
    case: dict[str, Any],
    response: str,
    universe: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Outcome metrics for one case, in the shape `evaluate_tool_calls` uses."""
    expected_outcome = case.get("expected_outcome") or {}
    return {
        "expected_count": expected_outcome.get("count"),
        "answer_recall": answer_recall(expected_outcome, response),
        "answer_precision": answer_precision(expected_outcome, response, universe),
        "hallucinated_entities": hallucinated_entities(response, universe),
        "outcome_success": outcome_success(expected_outcome, response, universe),
    }
