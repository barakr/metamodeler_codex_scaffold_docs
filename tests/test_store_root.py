"""The store location is one explicit answer, not two implicit ones (D3).

Every registry and artifact path used to be a module constant relative to the process working
directory. Two consequences: running `bayesmm` from a different folder silently used a
different store, and the "is this registry entry inside the store" rule was written twice, with
different anchors — `Path.cwd()` in `run_store`, the registry's own directory in
`surrogate_store`. Both defensible; having both is not.

`store_root()` is now the single answer, and `MM_STORE_ROOT` names it. The default is
unchanged (the working directory), so nothing moves for anyone who does not set it — which is
the point: this makes the location *sayable*, it does not relocate anybody's data.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import bayesian_metamodeling.storage.run_store as run_store_mod
from bayesian_metamodeling.storage._root import STORE_ROOT_ENV_VAR, is_inside_store, store_root


class TestStoreRoot:
    def test_defaults_to_the_working_directory(self, monkeypatch, tmp_path):
        """The pre-D3 behaviour, preserved deliberately so no existing store moves."""
        monkeypatch.delenv(STORE_ROOT_ENV_VAR, raising=False)
        monkeypatch.chdir(tmp_path)
        assert store_root() == tmp_path.resolve()

    def test_env_var_pins_it_regardless_of_cwd(self, monkeypatch, tmp_path):
        """The actual fix: the store stops depending on where you launched from."""
        pinned = tmp_path / "pinned_store"
        pinned.mkdir()
        monkeypatch.setenv(STORE_ROOT_ENV_VAR, str(pinned))

        monkeypatch.chdir(tmp_path)
        from_parent = store_root()
        elsewhere = tmp_path / "some" / "subdir"
        elsewhere.mkdir(parents=True)
        monkeypatch.chdir(elsewhere)

        assert from_parent == store_root() == pinned.resolve(), (
            "MM_STORE_ROOT must pin the store; that is the whole reason it exists"
        )

    def test_expands_user_home(self, monkeypatch):
        monkeypatch.setenv(STORE_ROOT_ENV_VAR, "~")
        assert store_root() == Path.home().resolve()


class TestContainment:
    def test_accepts_a_path_under_the_root(self, monkeypatch, tmp_path):
        monkeypatch.setenv(STORE_ROOT_ENV_VAR, str(tmp_path))
        assert is_inside_store(tmp_path / "runs" / "abc" / "run.json")

    def test_rejects_a_path_outside_the_root(self, monkeypatch, tmp_path):
        monkeypatch.setenv(STORE_ROOT_ENV_VAR, str(tmp_path / "inside"))
        (tmp_path / "inside").mkdir()
        assert not is_inside_store(tmp_path / "outside" / "run.json")

    def test_the_rule_is_shared_by_the_run_registry(self, monkeypatch, tmp_path):
        """`show_registered_run` must use the shared rule, not its own copy of one."""
        registry = tmp_path / "reg.json"
        registry.write_text(json.dumps({"bad": "/etc/passwd"}))
        monkeypatch.setattr(run_store_mod, "REGISTRY_PATH", registry)
        monkeypatch.setenv(STORE_ROOT_ENV_VAR, str(tmp_path))

        with pytest.raises(ValueError, match="outside the store"):
            run_store_mod.show_registered_run("bad")

    def test_an_entry_inside_the_pinned_root_is_readable(self, monkeypatch, tmp_path):
        """The converse — the guard must not refuse legitimate entries."""
        record = tmp_path / "runs" / "r1" / "run.json"
        record.parent.mkdir(parents=True)
        record.write_text(json.dumps({"run_id": "r1", "status": "success"}))
        registry = tmp_path / "reg.json"
        registry.write_text(json.dumps({"r1": str(record)}))
        monkeypatch.setattr(run_store_mod, "REGISTRY_PATH", registry)
        monkeypatch.setenv(STORE_ROOT_ENV_VAR, str(tmp_path))

        assert run_store_mod.show_registered_run("r1")["run_id"] == "r1"
