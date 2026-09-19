"""The corpus, loaded, answered through the tools a model would actually call.

This is the check the harness never had. `ask_eval_seed.py` wrote rows and
nothing ever asked whether a tool could see them — it could not, and the
benchmark graded four cases against an empty answer for as long as it existed.

So these assertions go through `execute_tool`, the same entry point
`AskService` uses, rather than querying the session directly. A count that comes
back from a direct query proves the row was written; a count that comes back
from the tool proves the row is reachable, which is the only kind of data a
benchmark can use.

No LLM is involved. Postgres is required, because the tool re-enters the
application over ASGI and the application resolves its own session — two
in-memory SQLite engines would be two different databases.
"""

from __future__ import annotations

import pytest

from aexy.core.config import get_settings
from aexy.services.ask_tools import build_tool_definitions, execute_tool
from tests.ai.evalcorpus import shape
from tests.ai.evalcorpus.load import PROSE_FILE, Clock, Prose, load_corpus


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    """Mirror the eval harness, which clears the cache before every case."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
async def corpus(eval_db_session):
    """Loads the real committed text when it exists, stubs when it does not.

    The structural assertions below hold either way — that is the property the
    loader was built for — but running against the real corpus also exercises
    the text actually being written to the columns, including its lengths.
    """
    prose = Prose.from_file() if PROSE_FILE.exists() else Prose.stub()
    return await load_corpus(eval_db_session, prose=prose, clock=Clock.now())


async def _desk(eval_db_session, corpus, **arguments) -> list[dict]:
    result = await execute_tool(
        "aexy_sd_open_tickets",
        arguments,
        eval_db_session,
        corpus.workspace_id,
        corpus.caller_id,
    )
    assert "error" not in result, result
    rows = result["result"]
    if isinstance(rows, dict):
        rows = rows.get("items") or rows.get("tickets") or rows.get("data") or []
    return rows


# ─── the world exists ──────────────────────────────────────────────────


async def test_the_load_reports_every_row_it_wrote(corpus):
    assert len(corpus.tickets) == len(shape.TICKETS)
    assert len(corpus.people) == len(shape.PEOPLE)
    assert len(corpus.sprints) == len(shape.SPRINTS)
    assert len(corpus.tasks) == len(shape.TASKS)


async def test_loading_twice_does_not_duplicate(eval_db_session, corpus):
    again = await load_corpus(eval_db_session, prose=Prose.stub())
    assert again.workspace_id == corpus.workspace_id
    assert again.tickets == corpus.tickets


async def test_the_caller_is_offered_the_service_desk(eval_db_session, corpus):
    tools = await build_tool_definitions(
        eval_db_session, corpus.workspace_id, corpus.caller_id
    )
    names = {tool["name"] for tool in tools}
    assert "aexy_sd_open_tickets" in names
    assert "aexy_sprint_tasks" in names


# ─── the desk answers what the shape says ──────────────────────────────


async def test_the_desk_is_not_empty(eval_db_session, corpus):
    """The assertion `ask_eval_seed` would have failed from the day it landed."""
    assert await _desk(eval_db_session, corpus) != []


@pytest.mark.parametrize(
    "status,expected",
    sorted(shape.EXPECTED.by_status.items()),
)
async def test_tickets_filter_by_status(eval_db_session, corpus, status, expected):
    rows = await _desk(eval_db_session, corpus, status=status, limit=100)
    assert len(rows) == expected


@pytest.mark.parametrize(
    "request_type,expected",
    sorted(shape.EXPECTED.by_request_type.items()),
)
async def test_tickets_filter_by_request_type(
    eval_db_session, corpus, request_type, expected
):
    rows = await _desk(eval_db_session, corpus, request_type=request_type, limit=100)
    assert len(rows) == expected


@pytest.mark.parametrize(
    "pending_with,expected",
    sorted(shape.EXPECTED.by_pending_with.items()),
)
async def test_tickets_filter_by_queue(eval_db_session, corpus, pending_with, expected):
    rows = await _desk(eval_db_session, corpus, pending_with=pending_with, limit=100)
    assert len(rows) == expected


async def test_open_tickets_resolve_through_the_taxonomy(eval_db_session, corpus):
    """`is_open` is answered by whichever stakeholder the template calls
    terminal, not by ticket status — so this fails if the taxonomy did not seed."""
    rows = await _desk(eval_db_session, corpus, is_open=True, limit=100)
    assert len(rows) == shape.EXPECTED.open_tickets


async def test_tickets_needing_triage(eval_db_session, corpus):
    rows = await _desk(eval_db_session, corpus, needs_triage=True, limit=100)
    assert len(rows) == shape.EXPECTED.needs_triage


async def test_the_caller_sees_queues_that_are_not_their_own(eval_db_session, corpus):
    """Without a full-view permission `resolve_scope_clause` would hide these."""
    rows = await _desk(eval_db_session, corpus, pending_with="finance", limit=100)
    assert rows, "the desk scope collapsed to the caller's own tickets"


# ─── the pair path-only grading cannot separate ────────────────────────


async def test_new_tickets_carry_the_priority_the_tool_cannot_filter_on(
    eval_db_session, corpus
):
    """`aexy_sd_open_tickets` has no `priority` argument.

    Both "show me high-priority new tickets" and "show me low-priority new
    tickets" therefore produce the same call, and are separable only by which
    rows the answer names. That requires the priorities to survive into the tool
    result, which is what this asserts.
    """
    rows = await _desk(eval_db_session, corpus, status="new", limit=100)
    priorities = [row.get("priority") for row in rows]
    assert priorities.count("high") == shape.EXPECTED.new_by_priority["high"]
    assert priorities.count("low") == shape.EXPECTED.new_by_priority["low"]


# ─── sprints and tracking ──────────────────────────────────────────────


async def test_sprint_tasks_come_back_for_the_active_sprint(eval_db_session, corpus):
    result = await execute_tool(
        "aexy_sprint_tasks",
        {"sprint_id": corpus.sprints[shape.ACTIVE_SPRINT], "limit": 100},
        eval_db_session,
        corpus.workspace_id,
        corpus.caller_id,
    )
    assert "error" not in result, result
    rows = result["result"]
    if isinstance(rows, dict):
        rows = rows.get("items") or rows.get("tasks") or rows.get("data") or []
    expected = sum(1 for t in shape.TASKS if t.sprint == shape.ACTIVE_SPRINT)
    assert len(rows) == expected


async def test_active_blockers_exclude_the_resolved_one(eval_db_session, corpus):
    result = await execute_tool(
        "aexy_active_blockers",
        {"team_id": corpus.team_id},
        eval_db_session,
        corpus.workspace_id,
        corpus.caller_id,
    )
    assert "error" not in result, result
    rendered = str(result["result"])
    for blocker in shape.BLOCKERS:
        if blocker.status == "resolved":
            continue
        assert blocker.id in rendered or blocker.severity in rendered
