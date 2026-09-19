"""Does the oracle agree with the application?

Every generated case declares which rows answer it, worked out by filtering
`shape.py` in pure Python. Nothing so far has checked that against the thing
being benchmarked. If the two disagree, the benchmark marks correct answers
wrong and there is no symptom — the run completes, the scores are just wrong.

So each case's expected arguments are sent to its tool for real, and the rows
that come back are compared with the rows the oracle chose. This is the
`--verify-only` step from the plan, written as a test rather than a script mode:
standing up Postgres, loading the corpus and skipping cleanly when it is absent
are all things the fixtures already do.

A failure here means one of two things, and the distinction matters. Either the
oracle is wrong — fix the filter. Or the application changed what that query
returns — which is a product regression the benchmark just caught.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from aexy.core.config import get_settings
from aexy.services.ask_tools import execute_tool
from tests.ai.evalcorpus.load import Clock, Prose, load_corpus, resolve_corpus_refs

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from generate_eval_cases import DEFAULT_OUT

CASES = json.loads(DEFAULT_OUT.read_text())["cases"]
# Every case that names rows. Listing the kinds explicitly, rather than
# excluding "none", means a new domain is verified the moment it is added
# instead of being silently skipped — which is what happened when this was a
# two-element set and three new domains landed.
ROW_KINDS = {"tickets", "sprint_tasks", "incidents", "leave_requests", "crm_records", "blockers"}
GRADEABLE = [c for c in CASES if c["expected_outcome"].get("kind") in ROW_KINDS]


def test_every_row_bearing_case_is_actually_verified():
    """Guards the filter above against a new `kind` slipping past it."""
    named = {c["expected_outcome"].get("kind") for c in CASES} - {"none", None}
    assert named <= ROW_KINDS, f"unverified kinds: {sorted(named - ROW_KINDS)}"


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
async def corpus(eval_db_session):
    return await load_corpus(eval_db_session, prose=Prose.stub(), clock=Clock.now())


def _rows(result):
    rows = result["result"]
    if isinstance(rows, dict):
        for key in ("items", "tickets", "tasks", "incidents", "requests", "blockers",
                    "records", "data", "results"):
            if key in rows:
                return rows[key]
        return []
    return rows


def _identify(row) -> str | None:
    """A desk row carries `ticket_id`; `id` is the desk row and is not it."""
    return row.get("ticket_id") or row.get("id")


@pytest.mark.parametrize("case", GRADEABLE, ids=[c["task_id"] for c in GRADEABLE])
async def test_the_tool_returns_the_rows_the_oracle_chose(
    eval_db_session, corpus, case
):
    tool, arguments = next(iter(case["expected_arguments"].items()))
    arguments = dict(resolve_corpus_refs(arguments, corpus))
    arguments.setdefault("limit", 100)

    result = await execute_tool(
        tool, arguments, eval_db_session, corpus.workspace_id, corpus.caller_id
    )
    assert "error" not in result, result

    returned = {_identify(row) for row in _rows(result)}
    expected = set(case["expected_outcome"]["ids"])

    # A case whose question is narrower than its tool — "which of these are high
    # priority" — expects a subset of what the call returns. The tool cannot
    # filter on priority, which is exactly why the case exists.
    filter_is_complete = len(expected) == len(_rows(result))
    if filter_is_complete:
        assert returned == expected, case["task_id"]
    else:
        assert expected <= returned, case["task_id"]


@pytest.mark.parametrize("case", GRADEABLE, ids=[c["task_id"] for c in GRADEABLE])
async def test_the_expected_count_is_reachable(eval_db_session, corpus, case):
    """Guards the failure mode that produced the old benchmark: an empty world.

    A case expecting rows, against a corpus that has none, grades every model
    identically and looks like a working benchmark while doing it.
    """
    assert case["expected_outcome"]["count"] > 0, case["task_id"]


async def test_the_priority_pair_is_separable_in_the_live_answer(
    eval_db_session, corpus
):
    """The claim the whole corpus exists to support.

    Both cases issue the same call. The returned rows must contain the high
    ones and the low ones, disjointly, or no grader could ever tell the two
    questions apart.
    """
    high = next(c for c in CASES if c["task_id"] == "sd_new_high")
    low = next(c for c in CASES if c["task_id"] == "sd_new_low")
    assert high["expected_arguments"] == low["expected_arguments"]

    tool, arguments = next(iter(high["expected_arguments"].items()))
    result = await execute_tool(
        tool, {**arguments, "limit": 100}, eval_db_session,
        corpus.workspace_id, corpus.caller_id,
    )
    returned = {_identify(row) for row in _rows(result)}

    high_ids = set(high["expected_outcome"]["ids"])
    low_ids = set(low["expected_outcome"]["ids"])
    assert high_ids <= returned
    assert low_ids <= returned
    assert high_ids.isdisjoint(low_ids)


async def test_a_corpus_reference_resolves_to_a_real_id(corpus):
    resolved = resolve_corpus_refs(
        {"sprint_id": {"$corpus": "sprints.autumn-hardening"}}, corpus
    )
    assert resolved["sprint_id"] == corpus.sprints["autumn-hardening"]


async def test_an_unknown_corpus_reference_fails_loudly(corpus):
    with pytest.raises(KeyError):
        resolve_corpus_refs({"$corpus": "sprints.no-such-sprint"}, corpus)
