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
from aexy.core.config import get_settings

from tests.ai.fixtures.ask_eval_seed import ask_eval_seed  # noqa: F401
from tests.ai.utils.eval_metrics import evaluate_outcome, evaluate_tool_calls
from tests.ai.utils.eval_result import EvalResult

pytestmark = pytest.mark.local_llm

@pytest.fixture(autouse=True)
def _reset_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()

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
    / ".logs"
)

RESULTS_FILE = (
    RESULTS_DIR
    / f"ask_eval_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
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
    # Fall back to LLM_PROVIDER (the same var tests/ai/conftest.py's
    # liveness probe reads) rather than a second, independent default.
    # Two separate hardcoded defaults ("lmstudio" here vs "ollama" there,
    # or vice versa) let the probe and the actual eval run drift apart, so
    # the local_llm skip marker stops reflecting what will actually run.
    os.getenv("LLM_PROVIDER", "lmstudio"),
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

    # The generated fixture is an object carrying a `_meta` provenance block
    # beside its cases, the way every other generated file in this repo does
    # (`dump_app_catalog.py`, `dump_mcp_catalog.py`). A bare array is still
    # accepted so a hand-written file keeps working.
    if isinstance(cases, dict):
        cases = cases.get("cases")

    if not isinstance(cases, list):
        raise ValueError(
            "aexy_eval_cases.json must contain a JSON array, or an object "
            "with a `cases` array."
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


def load_universe() -> dict:
    """Every entity the corpus contains, for telling a wrong answer from an
    invented one.

    Written into the fixture by `scripts/generate_eval_cases.py`. A hand-written
    fixture has no such block, and the metrics then decline to call anything
    invented rather than guessing.
    """
    with CASES_FILE.open("r", encoding="utf-8") as file:
        data = json.load(file)
    if isinstance(data, dict):
        return data.get("_meta", {}).get("universe", {})
    return {}


def pytest_generate_tests(metafunc):
    if "case" in metafunc.fixturenames:
        cases = load_eval_cases()
        metafunc.parametrize(
            "case",
            cases,
            ids=[case["task_id"] for case in cases],
        )

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
    eval_db_session,
    seed: dict,
    run_index: int,
) -> EvalResult:
    """
    Execute one benchmark case through the real AskService.
    """

    task_id = case["task_id"]

    run_id = str(uuid4())

    provider_name = EVAL_PROVIDER

    base_result = {
            "run_id": run_id,
            "task_id": task_id,
            "run_index": run_index,
            "provider": provider_name,
            # Filled in below, once the real AskService reveals which model
            # and streaming family it actually resolved to.
            "model_version": EVAL_MODEL or "unknown",
            "git_sha": get_git_sha(),
            "prompt_version": "ask_system_prompt_v1",
            "judge_version": None,
            "pricing_version": None,
            "temperature": None,
            "top_p": None,
            "timestamp": datetime.now(
                timezone.utc
            ).isoformat(),
        }
    try:

        # --------------------------------------------------------------------
        # 1. CREATE ASK SERVICE
        # --------------------------------------------------------------------

        service = AskService(
            db=eval_db_session,
        )

        # --------------------------------------------------------------------
        # 2. CREATE A NEW CONVERSATION
        # --------------------------------------------------------------------

        conversation = await service.create_conversation(
            workspace_id=seed["workspace_id"],
            developer_id=seed["developer_id"],
            title=f"AexyEval {task_id}",
        )

        await eval_db_session.flush()

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
        # 4b. VERIFY PROVIDER, RECORD ACTUAL MODEL/TEMPERATURE
        # --------------------------------------------------------------------
        #
        # AskService resolves its provider/model lazily, inside
        # stream_response() on its first iteration (it depends on the
        # workspace: kill switch, BYOK, per-feature overrides). service._provider
        # is "none" until the stream above has actually run, so this check
        # has to happen after the stream completes, not right after
        # construction.

        expected_family = {
            "claude": "anthropic",
            "anthropic": "anthropic",
            "openai": "openai",
            "gemini": "gemini",
            "deepseek": "openai",
            "openrouter": "openai",
            "lmstudio": "openai",
            # Ollama exposes an OpenAI-compatible API, so AskService routes
            # it through the same "openai" streaming family (see
            # aexy.llm.resolution.platform_config).
            "ollama": "openai",
        }[provider_name]

        if service._provider != expected_family:
            raise RuntimeError(
                f"Requested provider {provider_name!r}, "
                f"but AskService resolved to {service._provider!r}."
            )

        # Record the model AskService actually resolved to (not just the
        # requested env var) and the temperature it will actually send. This
        # harness always pins LLM_TEMPERATURE=0 above, so service._temperature
        # is set; the per-family fallback below only matters if that pin is
        # ever removed, mirroring AskService's own "use my override, else
        # each path's own default" logic.
        base_result["model_version"] = service._model or EVAL_MODEL or "unknown"
        base_result["temperature"] = (
            service._temperature
            if service._temperature is not None
            else (1.0 if service._provider == "anthropic" else 0.7)
        )

        # --------------------------------------------------------------------
        # 5. LOAD SAVED ASSISTANT MESSAGE
        # --------------------------------------------------------------------

        statement = select(
            AskMessage
        ).where(
            AskMessage.id == final_message_id
        )

        db_result = await eval_db_session.execute(
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

        path_ok = metrics["path_success"] and not metrics["iterations_exceeded"]

        # --------------------------------------------------------------------
        # 8. DETERMINE CURRENT TASK SUCCESS
        # --------------------------------------------------------------------

        grading_mode = case.get(
            "grading_mode",
            "both",
        )

        # Outcome grading is what separates two questions that produce the same
        # call. `aexy_sd_open_tickets` has no `priority` argument, so "which new
        # tickets are high priority" and "which are low priority" are identical
        # on the path and differ only in the rows the answer names.
        outcome = evaluate_outcome(
            case=case,
            response=response_text,
            universe=load_universe(),
        )

        outcome_ok = outcome["outcome_success"]

        if grading_mode == "path":

            task_success = path_ok

        elif grading_mode == "both":

            task_success = path_ok and outcome_ok

        elif grading_mode == "outcome":

            task_success = outcome_ok

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
            **base_result,
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

            outcome_success=outcome_ok,

            task_success=task_success,

            error=None,

            # ---------------------------------------------------------------
            # Additional metadata
            # ---------------------------------------------------------------

            metadata={
                "grading_mode": grading_mode,

                "answer_recall": outcome["answer_recall"],

                "answer_precision": outcome["answer_precision"],

                "hallucinated_entities":
                    outcome["hallucinated_entities"],

                "expected_count": outcome["expected_count"],

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
            **base_result,

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

            outcome_success=outcome_ok,

            task_success=False,

            # Some exceptions (asyncio.TimeoutError, CancelledError) stringify
            # to "" -- record the type too, or a failed run looks identical
            # to a successful one in the printed summary and JSONL.
            error=f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__,

            metadata={},
        )


# ============================================================================
# PYTEST TEST
# ============================================================================

async def test_ask_eval_case(
    case,
    eval_db_session,
    ask_eval_seed,
    monkeypatch,
):
    """
    Execute one AexyEval benchmark case.

    Model-quality failures are recorded as benchmark results.

    Pytest fails only when there is a harness/runtime error.
    """

    provider_name = EVAL_PROVIDER.lower().strip()

    supported_providers = {
        "claude",
        "anthropic",
        "openai",
        "gemini",
        "deepseek",
        "openrouter",
        "lmstudio",
        "ollama",
    }

    if provider_name not in supported_providers:
        pytest.fail(
            f"Unsupported evaluation provider: {provider_name}"
        )

    monkeypatch.setenv(
        "LLM_PROVIDER",
        provider_name,
    )

    if EVAL_MODEL:
        model_env = {
            "claude": "LLM_MODEL",
            "anthropic": "LLM_MODEL",
            "gemini": "GEMINI_MODEL",
            "openai": "OPENAI_MODEL",
            "deepseek": "LLM_MODEL",
            "openrouter": "OPENROUTER_MODEL",
            "lmstudio": "LMSTUDIO_MODEL",
            "ollama": "OLLAMA_MODEL",
        }[provider_name]

        monkeypatch.setenv(
            model_env,
            EVAL_MODEL,
        )

    # Pin sampling to 0 for eval runs. A single run of a stochastic model at
    # a non-zero temperature isn't a score -- it's one sample. Pinning to 0
    # makes that one run deterministic and reproducible instead; the
    # alternative (repeating each case N times and reporting a pass rate)
    # is real future work but out of scope for this harness-validation pass.
    monkeypatch.setenv("LLM_TEMPERATURE", "0")

    # get_settings() is cached, so force it to read
    # the temporary environment values above.
    get_settings.cache_clear()

    settings = get_settings()
    llm = settings.llm

    anthropic_key = (
        settings.anthropic_api_key
        or llm.anthropic_api_key
    )

    provider_keys = {
        "claude": anthropic_key,
        "anthropic": anthropic_key,
        "openai": llm.openai_api_key,
        "gemini": llm.gemini_api_key,
        "deepseek": llm.deepseek_api_key,
        "openrouter": llm.openrouter_api_key,
    }

    if (
        provider_name in provider_keys
        and not provider_keys[provider_name]
    ):
        pytest.skip(
            f"{provider_name} requested for evaluation, "
            "but its API key is not configured."
        )

    result = await run_ask_case(
        case=case,
        eval_db_session=eval_db_session,
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