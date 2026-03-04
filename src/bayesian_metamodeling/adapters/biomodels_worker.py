"""Worker script that simulates SBML with libroadrunner."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _load_roadrunner():
    try:
        import roadrunner
    except ImportError as exc:
        raise RuntimeError(
            "libroadrunner is required for biomodels simulation. Install package 'libroadrunner'."
        ) from exc
    return roadrunner


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sbml-path", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--params-json", required=True)
    parser.add_argument("--time-grid-json", required=True)
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    out_dir = run_dir / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    params = json.loads(args.params_json)
    time_grid = json.loads(args.time_grid_json)

    roadrunner = _load_roadrunner()
    rr = roadrunner.RoadRunner(args.sbml_path)

    for key, value in params.items():
        rr.setGlobalParameterByName(key, float(value))

    t0 = float(time_grid.get("t0", 0.0))
    t1 = float(time_grid.get("t1", 10.0))
    if "n_points" in time_grid and time_grid["n_points"] is not None:
        n_points = int(time_grid["n_points"])
    elif "dt" in time_grid and time_grid["dt"] is not None:
        dt = float(time_grid["dt"])
        n_points = int((t1 - t0) / dt) + 1
    else:
        n_points = 101

    species = list(rr.model.getFloatingSpeciesIds())
    selections = ["time", *species]
    result = rr.simulate(t0, t1, n_points, selections=selections)

    rows = []
    for row in result:
        rows.append(
            {str(result.colnames[idx]): float(row[idx]) for idx in range(len(result.colnames))}
        )

    payload = {
        "columns": [str(c) for c in result.colnames],
        "n_points": n_points,
        "t0": t0,
        "t1": t1,
        "rows": rows,
    }
    (out_dir / "timeseries.json").write_text(json.dumps(payload, indent=2, sort_keys=True))
    print(json.dumps({"status": "ok", "n_points": n_points, "species_count": len(species)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
