"""A sweep must succeed when `bayesmm` is invoked from outside the repo root.

Regression test for a silent-output-loss bug found on 2026-08-07.

`_run_single_point` built its run directory as `Path(spec.storage.root)/...`,
which is relative. The adapter hands that string to the model as `--run-dir`, but
the model subprocess runs with `cwd=REPO_ROOT` — not with the cwd of the process
that invoked `bayesmm`. So the two resolved differently: the model wrote its
outputs under REPO_ROOT while `parse_outputs` looked under the invoking cwd, and
every point failed with "Output parsing failed: No such file or directory". The
outputs existed; nobody looked where they were.

It went unnoticed because every test and example invoked the CLI from the repo
root, which makes the two paths coincide. It surfaced only when the
`projects/tcr_signaling` notebooks ran it from the submodule root, where 21/21
and 64/64 points failed.

The fix resolves the run directory to an absolute path. This test pins the
property that matters — a sweep works from an arbitrary cwd — rather than the
implementation detail.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

import bayesian_metamodeling.storage.run_store as run_store
from bayesian_metamodeling.cli.main import main

REPO_ROOT = Path(__file__).resolve().parents[1]
TOY_SPEC = REPO_ROOT / "tutorials" / "specs" / "model.toy.grid.json"


@pytest.mark.integration
def test_sweep_succeeds_when_invoked_from_a_foreign_cwd(monkeypatch, tmp_path, capsys):
    if not TOY_SPEC.is_file():
        pytest.skip(f"toy spec missing at {TOY_SPEC}")

    payload = json.loads(TOY_SPEC.read_text(encoding="utf-8"))
    # Relative, as the spec validator requires. Resolved against whatever cwd the
    # CLI runs in — which is the whole point of the test.
    payload["storage"] = {"root": "store_from_foreign_cwd"}
    spec_path = tmp_path / "toy.json"
    spec_path.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(run_store, "REGISTRY_PATH", tmp_path / "registry.json")
    # The bug's trigger: run from somewhere that is NOT the repo root.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["mm", "run", str(spec_path)])

    code = main()
    out = capsys.readouterr().out
    assert code == 0, f"sweep exited {code} from cwd={tmp_path}:\n{out}"
    assert "0 successful runs" not in out, (
        f"every point failed when invoked from {tmp_path} — the model's outputs and "
        f"parse_outputs disagreed about where the run directory is.\n{out}"
    )

    sweeps = sorted((tmp_path / "store_from_foreign_cwd" / "sweeps").glob("*/sweep_rows.csv"))
    assert sweeps, "no sweep_rows.csv written under the foreign cwd's storage root"
    # `with`, not a bare .open() handed to DictReader: the handle would never be
    # closed, and `filterwarnings = error` turns that ResourceWarning into a
    # failure attributed to whichever test is running when GC fires.
    with sweeps[-1].open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    successes = [r for r in rows if r.get("status") == "success"]
    assert successes, (
        f"{len(rows)} points ran and none succeeded. First error: "
        f"{(rows[0].get('error') or '')[:200]}"
    )
    assert len(successes) == len(rows), f"{len(rows) - len(successes)}/{len(rows)} points failed"
