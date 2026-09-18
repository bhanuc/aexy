"""No cached engine may outlive the event loop that created it.

`aexy.core.database` caches one engine per PID deliberately — forked workers need
that. In tests it was a hazard: pytest-asyncio gives every test its own loop, and
aiosqlite and asyncpg both bind a connection to the loop that opened it. The
readiness check reaches `get_async_session`, so the first test to hit it left a
cached engine that 76 later tests then drove from a loop that no longer existed.

The symptom was not a clean error. It was values arriving mid-flush with entirely
the wrong type — `'float' object has no attribute 'replace'` raised inside
`uuid.UUID.__init__`, or a `uuid.UUID` instance with no `int` attribute — in
whichever unrelated test happened to be running when it went wrong. One arbitrary
red test per full-suite run, passing whenever that file was run alone.

These tests guard the fixture that fixes it, because the failure it prevents
cannot be reproduced on demand and would come back unnoticed.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from aexy.core import database


def test_the_cache_is_empty_while_a_test_runs():
    """The autouse fixture clears it on the way in.

    If this ever fails, some earlier test's engine is still cached — and every
    call site of `get_async_session` in this test is talking to a connection
    bound to a dead loop.
    """
    assert database._engine_cache == {}
    assert database._sync_engine_cache == {}


@pytest.mark.asyncio
async def test_an_engine_this_test_creates_does_not_escape_it():
    """Creating one here is fine; what matters is that it does not survive.

    Asserted by the *next* test's copy of the check above — this one only proves
    the cache is populated by ordinary use, so the clearing has something to do.
    """
    database.get_engine()
    assert database._engine_cache != {}


def test_the_previous_test_left_nothing_behind():
    # Named to run after the one above (pytest preserves file order), which is
    # what makes this pair an actual test of the teardown rather than of setup.
    assert database._engine_cache == {}


class TestTheFixtureItself:
    def test_it_is_autouse_or_it_protects_nothing(self):
        source = Path("tests/conftest.py").read_text()
        assert "_no_engine_outlives_its_event_loop" in source
        # An opt-in fixture would leave every test that forgot it exposed, and
        # the tests that get hurt are never the ones that know about this.
        index = source.index("_no_engine_outlives_its_event_loop")
        preceding = source[max(0, index - 200) : index]
        assert "autouse=True" in preceding

    def test_it_clears_both_caches(self):
        """The sync cache is the same trap: `get_sync_session` is used by
        background paths, and a psycopg2 connection cached across tests is a
        connection shared between them."""
        source = Path("tests/conftest.py").read_text()
        body = source[source.index("_no_engine_outlives_its_event_loop") :][:3000]
        assert body.count("_engine_cache.clear()") >= 2
        assert body.count("_sync_engine_cache.clear()") >= 2

    def test_disposal_cannot_fail_a_test(self):
        """Teardown runs after loops have sometimes already closed, and disposing
        an engine bound to a closed loop raises. A leaked connection in a test
        process is much better than a failed teardown that hides the real
        assertion."""
        source = Path("tests/conftest.py").read_text()
        body = source[source.index("_no_engine_outlives_its_event_loop") :][:3000]
        assert "except Exception:" in body

    def test_the_cache_is_still_per_pid_in_production(self):
        """The fixture must not have been "fixed" by removing the cache. Forked
        workers cannot share an asyncpg connection, which is why it exists."""
        assert isinstance(database._engine_cache, dict)
        assert "pid" in inspect.getsource(database._get_engine)


class TestDisposalOfPerLoopEngines:
    """`_get_engine` keys on the running loop, so a sync caller that spins up a
    loop gets an engine nothing else will ever close.

    The trap is that the disposal has to be resolved *from inside* the loop. The
    obvious spelling — `get_engine()` in a `finally`, where no loop is running —
    resolves `_engine_cache_no_loop` instead, disposes an engine that never
    served a query, and leaves the real one holding its connections. Two call
    sites shipped exactly that, so these tests pin the behaviour rather than the
    spelling.
    """

    def test_repeated_runs_do_not_accumulate_engines(self):
        """The leak, stated directly: N calls must not leave N engines cached.

        Without disposal this grows by one entry per call, each holding a pool
        of up to `pool_size + max_overflow` connections.
        """

        async def _work():
            database.get_engine()

        for _ in range(5):
            database.run_in_new_event_loop(_work())

        cached = sum(len(per_loop) for per_loop in database._engine_cache.values())
        assert cached == 0, f"{cached} engine(s) survived their event loop"

    def test_it_disposes_the_engine_that_actually_ran(self):
        """Not merely *an* engine. `dispose()` swaps the pool for a fresh one,
        so a changed pool identity is the observable proof that this engine —
        the one the coroutine used — is the one that was disposed."""
        seen = {}

        async def _work():
            engine = database.get_engine()
            seen["engine"] = engine
            seen["pool"] = engine.pool

        database.run_in_new_event_loop(_work())

        assert seen["engine"].pool is not seen["pool"]

    def test_it_never_resolves_the_no_loop_cache(self):
        """The original bug in one assertion. Disposing from sync context
        populates `_engine_cache_no_loop` with an engine created purely to be
        thrown away; nothing on this path should ever touch it."""

        async def _work():
            database.get_engine()

        database.run_in_new_event_loop(_work())

        assert database._engine_cache_no_loop == {}

    def test_a_failing_coroutine_still_disposes(self):
        """A task that raises is exactly when disposal matters most: the
        exception propagates, and the retry that follows gets a fresh loop."""

        async def _boom():
            database.get_engine()
            raise RuntimeError("task failed")

        with pytest.raises(RuntimeError, match="task failed"):
            database.run_in_new_event_loop(_boom())

        cached = sum(len(per_loop) for per_loop in database._engine_cache.values())
        assert cached == 0

    def test_no_other_module_drives_its_own_event_loop(self):
        """Structural, because the failure is invisible at the call site: a new
        `asyncio.new_event_loop()` anywhere in `src/` silently reintroduces the
        leak, and nothing about the code that does it looks wrong.

        `run_in_new_event_loop` is the one place allowed to create a loop,
        because it is the one place that disposes what the loop created.
        """
        offenders = sorted(
            str(path.relative_to("src"))
            for path in Path("src/aexy").rglob("*.py")
            if "new_event_loop()" in path.read_text()
            and path.name != "database.py"
        )
        assert offenders == [], (
            "these modules create their own event loop instead of calling "
            f"aexy.core.database.run_in_new_event_loop: {offenders}"
        )
