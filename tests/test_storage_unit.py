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
    with pytest.raises(ValueError, match="outside project"):
        show_registered_run("bad")
