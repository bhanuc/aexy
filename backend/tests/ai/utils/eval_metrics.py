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

        matching_call = next(
            (
                call
                for call in actual_tool_calls
                if call.get("tool_name") == tool_name
            ),
            None,
        )

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
    acceptable_tool_sets: list[list[str]],
    expected_arguments: dict[str, dict[str, Any]],
    forbidden_actions: list[str],
    actual_tool_calls: list[dict[str, Any]],
    minimum_argument_accuracy: float = 1.0,
) -> bool:
    """
    Determine whether the model followed an acceptable execution path.

    Path success requires:

    1. tool selection fully matches one acceptable tool set
    2. expected tool arguments are correct
    3. no forbidden tool/action was used
    4. all tool executions succeeded
    """

    actual_tools = [
        call.get("tool_name")
        for call in actual_tool_calls
        if call.get("tool_name")
    ]

    best_expected_set = select_best_tool_set(
        acceptable_tool_sets=acceptable_tool_sets,
        actual_tools=actual_tools,
    )

    selection_score = tool_f1(
        expected_tools=best_expected_set,
        actual_tools=actual_tools,
    )

    args_score = argument_accuracy(
        expected_arguments=expected_arguments,
        actual_tool_calls=actual_tool_calls,
    )

    forbidden_used = has_forbidden_action(
        forbidden_actions=forbidden_actions,
        actual_tools=actual_tools,
    )

    tools_succeeded = all_tools_successful(
        actual_tool_calls=actual_tool_calls,
    )

    return (
        selection_score == 1.0
        and args_score >= minimum_argument_accuracy
        and not forbidden_used
        and tools_succeeded
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

    forbidden_actions = case.get(
        "forbidden_actions",
        [],
    )

    actual_tools = [
        call.get("tool_name")
        for call in actual_tool_calls
        if call.get("tool_name")
    ]

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
        acceptable_tool_sets=acceptable_tool_sets,
        expected_arguments=expected_arguments,
        forbidden_actions=forbidden_actions,
        actual_tool_calls=actual_tool_calls,
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

        "path_success": successful_path,
    }