"""
Standard result schema for AexyEval benchmark runs.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class EvalResult:
    """
    Standard result object produced by one AexyEval run.
    """

    # Benchmark identity
    run_id: str
    task_id: str
    run_index: int

    # Model identity
    provider: str
    model_version: str

    # Reproducibility metadata
    git_sha: str | None = None
    prompt_version: str | None = None
    judge_version: str | None = None
    pricing_version: str | None = None

    temperature: float | None = None
    top_p: float | None = None
    timestamp: str | None = None

    # Ask AI output
    response: str = ""

    tool_calls: list[dict[str, Any]] = field(
        default_factory=list
    )

    # Token usage
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        """
        Return total input + output token usage.
        """
        return self.input_tokens + self.output_tokens

    # Timing
    latency_ms: int = 0

    # AskService does not measure TTFT yet.
    ttft_ms: int | None = None

    # Deterministic tool metrics
    tool_precision: float = 0.0
    tool_recall: float = 0.0
    tool_f1: float = 0.0
    argument_accuracy: float = 0.0

    forbidden_tool_rate: float = 0.0
    failed_tool_rate: float = 0.0

    # Success indicators
    path_success: bool = False

    # Outcome grading will be added later.
    outcome_success: bool | None = None

    task_success: bool = False

    # Failure information
    error: str | None = None

    # Optional raw metadata
    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        """
        Convert EvalResult to a serializable dictionary.
        """

        result = asdict(self)

        # Include computed total token count.
        result["total_tokens"] = self.total_tokens

        return result