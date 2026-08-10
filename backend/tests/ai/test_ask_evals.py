"""
End-to-end Ask AI evaluation tests for AexyEval.

Pipeline:

    Load benchmark case
        ↓
    Use deterministic seeded database
        ↓
    Create Ask conversation
        ↓
    Run real AskService
        ↓
    Consume SSE stream
        ↓
    Retrieve final AskMessage
        ↓
    Evaluate tool calls
        ↓
    Build EvalResult
        ↓
    Save result to JSONL
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select

from aexy.models.ask import AskMessage
from aexy.services.ask_service import AskService

from tests.ai.fixtures.ask_eval_seed import ask_eval_seed  # noqa: F401
from tests.ai.utils.eval_metrics import evaluate_tool_calls
from tests.ai.utils.eval_result import EvalResult


# ============================================================================
# PATHS
# ============================================================================

CURRENT_DIR = Path(__file__).resolve().parent

CASES_FILE = (
    CURRENT_DIR
    / "fixtures"
    / "aexy_eval_cases.json"
)

RESULTS_DIR = (
    CURRENT_DIR
    / "results"
)

RESULTS_FILE = (
    RESULTS_DIR
    / "ask_eval_results.jsonl"
)


# ============================================================================
# EVALUATION CONFIGURATION
# ============================================================================

# These can be overridden from the terminal.
#
# Example:
#
# AEXY_EVAL_PROVIDER=lmstudio \
# AEXY_EVAL_MODEL=qwen2.5-7b-instruct \
# PYTHONPATH=src \
# pytest tests/ai/test_ask_evals.py -s

EVAL_PROVIDER = os.getenv(
    "AEXY_EVAL_PROVIDER",
    "lmstudio",
)

EVAL_MODEL = os.getenv(
    "AEXY_EVAL_MODEL",
)

# Initial harness validation:
# one run per case.
#
# Later repetition logic should be moved to eval_runner.py.
RUN_INDEX = 0


# ============================================================================
# LOAD BENCHMARK CASES
# ============================================================================

def load_eval_cases() -> list[dict]:
    """
    Load benchmark cases from aexy_eval_cases.json.
    """

    if not CASES_FILE.exists():
        raise FileNotFoundError(
            f"Evaluation case file not found: {CASES_FILE}"
        )

    with CASES_FILE.open(
        "r",
        encoding="utf-8",
    ) as file:
        cases = json.load(file)

    if not isinstance(cases, list):
        raise ValueError(
            "aexy_eval_cases.json must contain a JSON array."
        )

    if not cases:
        raise ValueError(
            "aexy_eval_cases.json contains no evaluation cases."
        )

    for index, case in enumerate(cases):
        if "task_id" not in case:
            raise ValueError(
                f"Case at index {index} has no task_id."
            )

        if "prompt" not in case:
            raise ValueError(
                f"Case {case['task_id']} has no prompt."
            )

    return cases


EVAL_CASES = load_eval_cases()


# ============================================================================
# SSE PARSER
# ============================================================================

def parse_sse_chunk(
    chunk: str,
) -> dict | None:
    """
    Parse one SSE chunk emitted by AskService.

    AskService emits strings such as:

        data: {"type": "text_delta", "text": "Hello"}

    Returns:
        Parsed dictionary, or None if the chunk cannot be parsed.
    """

    if not chunk:
        return None

    chunk = chunk.strip()

    if not chunk.startswith("data: "):
        return None

    raw_json = chunk[len("data: "):]

    try:
        return json.loads(raw_json)

    except json.JSONDecodeError:
        return None


# ============================================================================
# GIT SHA
# ============================================================================

def get_git_sha() -> str | None:
    """
    Return the current git commit SHA.

    Returns None when git information is unavailable.
    """

    try:
        backend_root = (
            Path(__file__)
            .resolve()
            .parents[2]
        )

        result = subprocess.run(
            [
                "git",
                "rev-parse",
                "HEAD",
            ],
            cwd=backend_root,
            capture_output=True,
            text=True,
            check=True,
        )

        return result.stdout.strip()

    except (
        subprocess.CalledProcessError,
        FileNotFoundError,
    ):
        return None


# ============================================================================
# SAVE RESULT
# ============================================================================

def save_eval_result(
    result: EvalResult,
) -> None:
    """
    Append one EvalResult to a JSONL file.
    """

    RESULTS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    with RESULTS_FILE.open(
        "a",
        encoding="utf-8",
    ) as file:

        file.write(
            json.dumps(
                result.to_dict(),
                ensure_ascii=False,
                default=str,
            )
        )

        file.write("\n")


# ============================================================================
# RUN ONE CASE
# ============================================================================

async def run_ask_case(
    *,
    case: dict,
    ai_db_session,
    seed: dict,
    run_index: int,
) -> EvalResult:
    """
    Execute one benchmark case through the real AskService.
    """

    task_id = case["task_id"]

    run_id = str(uuid4())

    provider_name = EVAL_PROVIDER

    try:

        # --------------------------------------------------------------------
        # 1. CREATE ASK SERVICE
        # --------------------------------------------------------------------

        service = AskService(
            db=ai_db_session,
            provider_override=provider_name,
            model_override=EVAL_MODEL,
        )

        # --------------------------------------------------------------------
        # 2. CREATE A NEW CONVERSATION
        # --------------------------------------------------------------------

        conversation = await service.create_conversation(
            workspace_id=seed["workspace_id"],
            developer_id=seed["developer_id"],
            title=f"AexyEval {task_id}",
        )

        await ai_db_session.flush()

        # --------------------------------------------------------------------
        # 3. RUN REAL ASK AI
        # --------------------------------------------------------------------

        final_message_id: str | None = None

        stream_error: str | None = None

        async for chunk in service.stream_response(
            conversation_id=str(conversation.id),
            workspace_id=seed["workspace_id"],
            developer_id=seed["developer_id"],
            user_content=case["prompt"],
        ):

            event = parse_sse_chunk(chunk)

            if event is None:
                continue

            event_type = event.get("type")

            # ---------------------------------------------------------------
            # Explicit AskService error
            # ---------------------------------------------------------------

            if event_type == "error":

                stream_error = event.get(
                    "message",
                    "Unknown AskService error",
                )

            # ---------------------------------------------------------------
            # Final event
            # ---------------------------------------------------------------

            elif event_type == "done":

                final_message_id = event.get(
                    "message_id"
                )

        # --------------------------------------------------------------------
        # 4. VERIFY STREAM FINISHED
        # --------------------------------------------------------------------

        if stream_error:

            raise RuntimeError(
                stream_error
            )

        if final_message_id is None:

            raise RuntimeError(
                "AskService stream completed without "
                "returning a final message_id."
            )

        # --------------------------------------------------------------------
        # 5. LOAD SAVED ASSISTANT MESSAGE
        # --------------------------------------------------------------------

        statement = select(
            AskMessage
        ).where(
            AskMessage.id == final_message_id
        )

        db_result = await ai_db_session.execute(
            statement
        )

        assistant_message = (
            db_result.scalar_one_or_none()
        )

        if assistant_message is None:

            raise RuntimeError(
                f"Assistant message {final_message_id} "
                "was not found in the database."
            )

        # --------------------------------------------------------------------
        # 6. EXTRACT MODEL OUTPUT
        # --------------------------------------------------------------------

        response_text = (
            assistant_message.content
            or ""
        )

        actual_tool_calls = (
            assistant_message.tool_calls
            or []
        )

        token_usage = (
            assistant_message.token_usage
            or {}
        )

        input_tokens = int(
            token_usage.get(
                "input_tokens",
                0,
            )
        )

        output_tokens = int(
            token_usage.get(
                "output_tokens",
                0,
            )
        )

        latency_ms = int(
            assistant_message.latency_ms
            or 0
        )

        # --------------------------------------------------------------------
        # 7. EVALUATE TOOL CALLS
        # --------------------------------------------------------------------

        metrics = evaluate_tool_calls(
            case=case,
            actual_tool_calls=actual_tool_calls,
        )

        path_ok = metrics[
            "path_success"
        ]

        # --------------------------------------------------------------------
        # 8. DETERMINE CURRENT TASK SUCCESS
        # --------------------------------------------------------------------

        grading_mode = case.get(
            "grading_mode",
            "both",
        )

        if grading_mode == "path":

            task_success = path_ok

        elif grading_mode == "both":

            # Outcome grading has not yet been implemented.
            #
            # For the initial harness, path success is used
            # temporarily as task success.
            task_success = path_ok

        elif grading_mode == "outcome":

            # Do not pretend outcome grading exists.
            task_success = False

        else:

            raise ValueError(
                f"Unsupported grading_mode: "
                f"{grading_mode}"
            )

        # --------------------------------------------------------------------
        # 9. BUILD STANDARD EVAL RESULT
        # --------------------------------------------------------------------

        result = EvalResult(
            # ---------------------------------------------------------------
            # Identity
            # ---------------------------------------------------------------

            run_id=run_id,

            task_id=task_id,

            run_index=run_index,

            # ---------------------------------------------------------------
            # Model
            # ---------------------------------------------------------------

            provider=provider_name,

            model_version=(
                service._model
                or "unknown"
            ),

            # ---------------------------------------------------------------
            # Reproducibility
            # ---------------------------------------------------------------

            git_sha=get_git_sha(),

            prompt_version=(
                "ask_system_prompt_v1"
            ),

            judge_version=None,

            pricing_version=None,

            # AskService currently uses temperature=0.7.
            temperature=0.7,

            top_p=None,

            timestamp=datetime.now(
                timezone.utc
            ).isoformat(),

            # ---------------------------------------------------------------
            # Response
            # ---------------------------------------------------------------

            response=response_text,

            tool_calls=actual_tool_calls,

            # ---------------------------------------------------------------
            # Tokens
            # ---------------------------------------------------------------

            input_tokens=input_tokens,

            output_tokens=output_tokens,

            # ---------------------------------------------------------------
            # Timing
            # ---------------------------------------------------------------

            latency_ms=latency_ms,

            # TTFT has not yet been added to AskService.
            ttft_ms=None,

            # ---------------------------------------------------------------
            # Tool metrics
            # ---------------------------------------------------------------

            tool_precision=metrics[
                "tool_precision"
            ],

            tool_recall=metrics[
                "tool_recall"
            ],

            tool_f1=metrics[
                "tool_f1"
            ],

            argument_accuracy=metrics[
                "argument_accuracy"
            ],

            forbidden_tool_rate=metrics[
                "forbidden_tool_rate"
            ],

            failed_tool_rate=metrics[
                "failed_tool_rate"
            ],

            # ---------------------------------------------------------------
            # Success
            # ---------------------------------------------------------------

            path_success=path_ok,

            outcome_success=None,

            task_success=task_success,

            error=None,

            # ---------------------------------------------------------------
            # Additional metadata
            # ---------------------------------------------------------------

            metadata={
                "grading_mode": grading_mode,

                "best_expected_tool_set":
                    metrics[
                        "best_expected_tool_set"
                    ],

                "actual_tools":
                    metrics[
                        "actual_tools"
                    ],

                "all_tools_successful":
                    metrics[
                        "all_tools_successful"
                    ],

                "message_id":
                    final_message_id,

                # DeepSeek, OpenRouter and LM Studio internally
                # reuse the OpenAI streaming path.
                "stream_family":
                    service._provider,
            },
        )

        return result

    except Exception as exc:

        # --------------------------------------------------------------------
        # Preserve failed benchmark runs too.
        # --------------------------------------------------------------------

        return EvalResult(
            run_id=run_id,

            task_id=task_id,

            run_index=run_index,

            provider=provider_name,

            model_version=(
                EVAL_MODEL
                or "unknown"
            ),

            git_sha=get_git_sha(),

            prompt_version=(
                "ask_system_prompt_v1"
            ),

            judge_version=None,

            pricing_version=None,

            temperature=0.7,

            top_p=None,

            timestamp=datetime.now(
                timezone.utc
            ).isoformat(),

            response="",

            tool_calls=[],

            input_tokens=0,

            output_tokens=0,

            latency_ms=0,

            ttft_ms=None,

            tool_precision=0.0,

            tool_recall=0.0,

            tool_f1=0.0,

            argument_accuracy=0.0,

            forbidden_tool_rate=0.0,

            failed_tool_rate=0.0,

            path_success=False,

            outcome_success=None,

            task_success=False,

            error=str(exc),

            metadata={},
        )


# ============================================================================
# PYTEST TEST
# ============================================================================

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    EVAL_CASES,
    ids=[
        case["task_id"]
        for case in EVAL_CASES
    ],
)
async def test_ask_eval_case(
    case,
    ai_db_session,
    ask_eval_seed,
):
    """
    Execute one AexyEval benchmark case.

    Model-quality failures are recorded as benchmark results.

    Pytest fails only when there is a harness/runtime error.
    """

    result = await run_ask_case(
        case=case,
        ai_db_session=ai_db_session,
        seed=ask_eval_seed,
        run_index=RUN_INDEX,
    )

    # ------------------------------------------------------------------------
    # SAVE RESULT
    # ------------------------------------------------------------------------

    save_eval_result(
        result
    )

    # ------------------------------------------------------------------------
    # PRINT PILOT RESULT
    # ------------------------------------------------------------------------

    print()
    print("=" * 70)

    print(
        f"AexyEval case: "
        f"{result.task_id}"
    )

    print(
        f"Provider: "
        f"{result.provider}"
    )

    print(
        f"Model: "
        f"{result.model_version}"
    )

    print(
        f"Tool precision: "
        f"{result.tool_precision:.3f}"
    )

    print(
        f"Tool recall: "
        f"{result.tool_recall:.3f}"
    )

    print(
        f"Tool F1: "
        f"{result.tool_f1:.3f}"
    )

    print(
        f"Argument accuracy: "
        f"{result.argument_accuracy:.3f}"
    )

    print(
        f"Forbidden tool rate: "
        f"{result.forbidden_tool_rate:.3f}"
    )

    print(
        f"Failed tool rate: "
        f"{result.failed_tool_rate:.3f}"
    )

    print(
        f"Path success: "
        f"{result.path_success}"
    )

    print(
        f"Task success: "
        f"{result.task_success}"
    )

    print(
        f"Latency: "
        f"{result.latency_ms} ms"
    )

    print(
        f"Input tokens: "
        f"{result.input_tokens}"
    )

    print(
        f"Output tokens: "
        f"{result.output_tokens}"
    )

    print(
        f"Total tokens: "
        f"{result.total_tokens}"
    )

    if result.error:

        print(
            f"ERROR: "
            f"{result.error}"
        )

    print("=" * 70)

    # ------------------------------------------------------------------------
    # IMPORTANT
    #
    # A wrong model answer should NOT fail pytest.
    #
    # We are benchmarking model quality.
    #
    # Pytest should fail only when the evaluation harness itself
    # cannot execute.
    # ------------------------------------------------------------------------

    assert result.error is None, (
        f"AexyEval harness failed for "
        f"{result.task_id}: "
        f"{result.error}"
    )