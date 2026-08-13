"""Unit tests for storage utilities including file locking, sha256, persist, and registry."""

from __future__ import annotations

import json
import threading

import pytest

import bayesian_metamodeling.storage.run_store as run_store_mod
from bayesian_metamodeling.spec import load_and_validate_modelspec
from bayesian_metamodeling.storage._filelock import locked_registry
from bayesian_metamodeling.storage.run_store import (
    list_registered_runs,
    persist_sweep,
    sha256_json,
    show_registered_run,
)


def _base_payload(storage_root: str = "tmp/test_store") -> dict:
    return {
        "schema_version": "1.0",
        "model": {
            "name": "test",
            "version": "1.0",
            "artifact": {"type": "local", "entrypoint": ["python", "x.py"]},
        },
        "runner": {
            "mode": "local_process",
            "resources": {"cpus": 1, "mem_gb": 1, "walltime_min": 1},
        },
        "io_schema": {
            "inputs": [{"name": "a", "type": "float", "units": "m"}],
            "outputs": [{"name": "y", "type": "float", "units": "m"}],
        },
        "design": {"strategy": "grid", "grid": {"a": [1.0]}},
        "adapter": {"id": "python_cli_adapter_v1"},
        "reproducibility": {"seed": 0},
        "storage": {"root": storage_root},
    }


# --- locked_registry ---


def test_locked_registry_concurrent_writes(tmp_path):
    """Spawn 4 threads writing to the same registry; verify all keys present."""
    registry_path = tmp_path / "registry.json"
    registry_path.write_text("{}")

    def _write_key(key: str) -> None:
        with locked_registry(registry_path):
            data = json.loads(registry_path.read_text())
            data[key] = f"value_{key}"
            registry_path.write_text(json.dumps(data))

    threads = [threading.Thread(target=_write_key, args=(f"k{i}",)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    result = json.loads(registry_path.read_text())
    assert set(result.keys()) == {"k0", "k1", "k2", "k3"}
    for i in range(4):
        assert result[f"k{i}"] == f"value_k{i}"


def test_locked_registry_under_contention_never_drops_a_writer(tmp_path):
    """Every thread must complete its write, and none may raise acquiring the lock.

    The 4-thread test above found a real bug on Windows and nothing else: because
    `msvcrt.locking()` locks per *process* rather than per descriptor, and `LK_LOCK`
    gives up after ten retries and raises, concurrent writers did not queue — they
    failed, and their entries vanished from the registry.

    This raises the contention and, crucially, asserts on *exceptions* as well as on
    the final contents. A dropped writer that happens not to change the key set would
    slip past a contents-only check.
    """
    registry_path = tmp_path / "registry.json"
    registry_path.write_text("{}")

    n = 16
    errors: list[BaseException] = []
    barrier = threading.Barrier(n)

    def _write_key(key: str) -> None:
        try:
            barrier.wait(timeout=30)  # maximise overlap rather than hoping for it
            with locked_registry(registry_path):
                data = json.loads(registry_path.read_text())
                data[key] = f"value_{key}"
                registry_path.write_text(json.dumps(data))
        except BaseException as exc:  # noqa: BLE001 - recorded and re-asserted below
            errors.append(exc)

    threads = [threading.Thread(target=_write_key, args=(f"k{i}",)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    assert not errors, f"{len(errors)} of {n} writers raised while locking: {errors[:3]}"
    assert not [t for t in threads if t.is_alive()], "a writer never finished — deadlock"
    result = json.loads(registry_path.read_text())
    assert set(result) == {f"k{i}" for i in range(n)}, (
        f"{n - len(result)} write(s) were silently lost under contention"
    )


# --- sha256 ---


def test_sha256_deterministic():
    payload = {"b": 2, "a": 1}
    assert sha256_json(payload) == sha256_json({"a": 1, "b": 2})


def test_sha256_different_payloads():
    assert sha256_json({"a": 1}) != sha256_json({"a": 2})


# --- persist_sweep ---


def test_persist_sweep_creates_artifacts(monkeypatch, tmp_path):
    registry_path = tmp_path / "reg.json"
    monkeypatch.setattr(run_store_mod, "REGISTRY_PATH", registry_path)

    storage_root = "tmp/sweep_test_store"
    payload = _base_payload(storage_root=storage_root)
    spec = load_and_validate_modelspec(payload)
    results = [
        {
            "point_index": 0,
            "point": {"a": 1.0},
            "status": "success",
            "returncode": 0,
            "outputs": {"y": 2.0},
            "error": "",
            "stdout": "",
            "stderr": "",
            "started_at": "2026-01-01T00:00:00",
            "finished_at": "2026-01-01T00:01:00",
            "duration_sec": 60.0,
        }
    ]
    stored = persist_sweep(
        spec_payload=payload,
        spec=spec,
        point_results=results,
        execution_mode="serial",
    )
    assert stored.run_id
    assert stored.run_dir.exists()
    assert (stored.run_dir / "sweep_rows.csv").exists()
    assert (stored.run_dir / "sweep_manifest.json").exists()


def test_persist_sweep_rejects_empty_results(monkeypatch, tmp_path):
    registry_path = tmp_path / "reg.json"
    monkeypatch.setattr(run_store_mod, "REGISTRY_PATH", registry_path)

    payload = _base_payload(storage_root="tmp/sweep_test_store2")
    spec = load_and_validate_modelspec(payload)
    with pytest.raises(ValueError, match="at least one"):
        persist_sweep(
            spec_payload=payload,
            spec=spec,
            point_results=[],
            execution_mode="serial",
        )


# --- list / show ---


def test_list_registered_runs_empty(monkeypatch, tmp_path):
    registry_path = tmp_path / "empty_reg.json"
    monkeypatch.setattr(run_store_mod, "REGISTRY_PATH", registry_path)
    assert list_registered_runs() == []


def test_show_registered_run_not_found(monkeypatch, tmp_path):
    registry_path = tmp_path / "empty_reg.json"
    registry_path.write_text("{}")
    monkeypatch.setattr(run_store_mod, "REGISTRY_PATH", registry_path)
    with pytest.raises(ValueError, match="not found"):
        show_registered_run("nonexistent")


def test_show_registered_run_rejects_path_outside_project(monkeypatch, tmp_path):
    registry_path = tmp_path / "bad_reg.json"
    registry_path.write_text(json.dumps({"bad": "/etc/passwd"}))
    monkeypatch.setattr(run_store_mod, "REGISTRY_PATH", registry_path)
    # Message changed with D3: the anchor is now the explicit store root
    # (storage/_root.py) rather than an ad-hoc `Path.cwd()` check written here. The
    # behaviour — refuse to read what a registry names outside the store — did not.
    with pytest.raises(ValueError, match="outside the store"):
        show_registered_run("bad")
