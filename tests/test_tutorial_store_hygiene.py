"""The tutorial suite must refuse to run against a leftover store (guard for the guard).

Background, because the failure mode is counter-intuitive: the tutorials hand data to each
other through `tmp/tutorials/toy_store` — T1 and T4 write it, T5 and T6 read it. On a machine
that has run the series before, that directory is already populated, so a notebook which would
fail in a clean checkout can pass locally by standing on data an earlier session left behind.

On 2026-08-12 `Tutorial_5` failed in Deep CI and **passed** here. It had no defect at all: its
surrogate fits on the store `Tutorial_1` produces, and `Tutorial_1` was crashing. The local run
did not merely miss the problem — it reported the opposite, which is worse than no check.

These tests are fast (no notebook is executed) because a guard nobody exercises is the next
thing to rot. In particular `test_snapshot_is_taken_before_any_notebook_runs` pins the subtle
part: the check must be a once-per-session snapshot, not a per-test one. Checking per-test
would fail tutorials 2-12 in *every* CI run, because `Tutorial_1` legitimately creates the very
directory being guarded.
"""

from __future__ import annotations

import tests.test_tutorial_integration as tut


def _redirect_store(monkeypatch, path):
    monkeypatch.setattr(tut, "TUTORIAL_STORE", path)
    monkeypatch.delenv(tut.ALLOW_DIRTY_ENV_VAR, raising=False)


def test_clean_checkout_is_allowed(monkeypatch, tmp_path):
    """No store at all — the normal CI condition."""
    _redirect_store(monkeypatch, tmp_path / "does_not_exist")
    assert tut._dirty_store_reason() is None


def test_empty_store_is_allowed(monkeypatch, tmp_path):
    """The directory existing is not the problem; earlier runs' data is."""
    store = tmp_path / "tutorials"
    store.mkdir()
    _redirect_store(monkeypatch, store)
    assert tut._dirty_store_reason() is None


def test_leftover_store_is_refused(monkeypatch, tmp_path):
    store = tmp_path / "tutorials"
    (store / "toy_store").mkdir(parents=True)
    _redirect_store(monkeypatch, store)

    reason = tut._dirty_store_reason()
    assert reason is not None, "a populated store must not be silently accepted"
    assert "toy_store" in reason, "the message must name what it found"
    assert "rm -rf" in reason, "the message must say how to fix it"
    assert tut.ALLOW_DIRTY_ENV_VAR in reason, "the message must name the override"


def test_override_is_honoured(monkeypatch, tmp_path):
    """An explicit opt-in is allowed — the point is that it must be explicit."""
    store = tmp_path / "tutorials"
    (store / "toy_store").mkdir(parents=True)
    monkeypatch.setattr(tut, "TUTORIAL_STORE", store)
    monkeypatch.setenv(tut.ALLOW_DIRTY_ENV_VAR, "1")
    assert tut._dirty_store_reason() is None


def test_it_fails_rather_than_skips(monkeypatch, tmp_path):
    """A skip and a pass look identical in a terminal; that is the whole defect class.

    `_dirty_store_reason` returning a string is what makes the caller `pytest.fail`. If this
    ever became a `pytest.skip`, a contaminated run would once again be indistinguishable
    from a good one (CLAUDE.md, "Guarding against silent no-ops").
    """
    store = tmp_path / "tutorials"
    (store / "toy_store").mkdir(parents=True)
    _redirect_store(monkeypatch, store)

    source = __import__("inspect").getsource(tut.test_tutorial_executes_and_self_check_passes)
    assert "pytest.fail(_DIRTY_STORE_AT_IMPORT)" in source, (
        "the dirty-store guard must FAIL, not skip — a skipped suite is indistinguishable "
        "from a passing one"
    )


def test_snapshot_is_taken_before_any_notebook_runs():
    """The check is once-per-session, not per-test — and that is load-bearing.

    `Tutorial_1` creates `tmp/tutorials/toy_store` as part of doing its job. A per-test check
    would therefore see a populated store from `Tutorial_2` onwards and fail tutorials 2-12 in
    every CI run, on a clean checkout. The question is only ever "was the store dirty when
    this session started".
    """
    source = __import__("inspect").getsource(tut.test_tutorial_executes_and_self_check_passes)
    assert "_dirty_store_reason()" not in source, (
        "the test must consult the import-time snapshot, not re-check the store per test — "
        "Tutorial_1 populates the directory being guarded"
    )
    assert hasattr(tut, "_DIRTY_STORE_AT_IMPORT")
