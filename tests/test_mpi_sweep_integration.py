import copy
import json
from pathlib import Path
from uuid import uuid4

import pytest

import bayesian_metamodeling.storage.run_store as run_store
from bayesian_metamodeling.cli.main import main


@pytest.mark.slow
@pytest.mark.integration
@pytest.mark.mpi
def test_mpi_mode_writes_single_centralized_sweep(monkeypatch, capsys):
    # `pytest.importorskip("mpi4py")` returns the package but does NOT pull
    # in the `MPI` submodule (mpi4py never auto-imports it on package import).
    # Skip on `mpi4py.MPI` directly so we get the real MPI module back.
    MPI = pytest.importorskip("mpi4py.MPI")
    comm = MPI.COMM_WORLD
    rank = comm.Get_rank()
    size = comm.Get_size()
    if size < 2:
        pytest.skip("MPI test requires >=2 ranks. Run with: mpirun -n 2 pytest -q -m mpi")

    token = comm.bcast(uuid4().hex if rank == 0 else None, root=0)
    shared_root = Path("tmp") / "pytest_mpi_sweep" / token
    spec_path = shared_root / "spec_mpi.json"
    registry_path = shared_root / "run_registry.json"

    if rank == 0:
        shared_root.mkdir(parents=True, exist_ok=True)
        payload = json.loads(Path("examples/toy_program/spec.toy_program.json").read_text())
        payload = copy.deepcopy(payload)
        payload["design"] = {"strategy": "grid", "grid": {"a": [0.0, 1.0], "b": [0.0, 1.0]}}
        payload["storage"] = {"root": str(shared_root / "store")}
        payload["runner"]["sweep_mode"] = "mpi"
        spec_path.write_text(json.dumps(payload))

    comm.Barrier()
    monkeypatch.setattr(run_store, "REGISTRY_PATH", registry_path)
    monkeypatch.setattr("sys.argv", ["mm", "run", str(spec_path)])
    code = main()
    comm.Barrier()

    if rank == 0:
        out = capsys.readouterr().out
        assert code == 0
        assert "Run complete: 4 successful runs" in out
        registry = json.loads(registry_path.read_text())
        assert len(registry) == 1
        run_id = next(iter(registry))
        run_record = json.loads(Path(registry[run_id]).read_text())
        assert Path(run_record["sweep_rows_path"]).exists()
    else:
        assert code == 0
