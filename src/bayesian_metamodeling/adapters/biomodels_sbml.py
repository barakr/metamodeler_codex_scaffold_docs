"""BioModels SBML adapter baseline implementation."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import requests

from bayesian_metamodeling.adapters.base import AdapterMaterialization
from bayesian_metamodeling.spec import ModelSpec

_OFFLINE_ENV_VAR = "MM_BIOMODELS_OFFLINE"


def _is_offline() -> bool:
    """Return True iff `MM_BIOMODELS_OFFLINE` is set to a truthy value."""
    return os.environ.get(_OFFLINE_ENV_VAR, "").strip().lower() in {"1", "true", "yes", "on"}


class BioModelsSBMLAdapter:
    id = "biomodels_sbml_adapter_v1"

    def _download_if_missing(
        self, *, spec: ModelSpec, cache_dir: Path, repo_root: Path | None = None
    ) -> Path:
        cache_dir.mkdir(parents=True, exist_ok=True)
        biomodels_id = spec.model.artifact.biomodels_id
        if biomodels_id is None:
            raise ValueError("biomodels_id is required for biomodels_sbml_adapter_v1")

        out_path = cache_dir / f"{biomodels_id}.xml"
        if out_path.exists():
            return out_path

        # Preferred offline path: a local SBML file pointed at by the spec.
        # Resolved against `repo_root` (or CWD as a fallback) so the spec stays
        # portable. Honored whether or not `MM_BIOMODELS_OFFLINE` is set.
        local_sbml = spec.model.artifact.local_sbml_path
        if local_sbml:
            base = repo_root or Path.cwd()
            local_path = (base / local_sbml).resolve()
            if not local_path.exists():
                raise FileNotFoundError(
                    f"model.artifact.local_sbml_path points to a non-existent file: "
                    f"{local_path} (relative source: {local_sbml!r})"
                )
            shutil.copy(local_path, out_path)
            return out_path

        # Offline mode: refuse to hit the network. Return an actionable error
        # with the cache target path and a curl recipe so the user can
        # pre-populate it themselves in restricted/sandboxed environments.
        if _is_offline():
            source_url = spec.model.artifact.source_url or (
                f"https://www.ebi.ac.uk/biomodels/model/download/{biomodels_id}"
                f"?filename={biomodels_id}_url.xml"
            )
            raise RuntimeError(
                f"BioModels offline mode ({_OFFLINE_ENV_VAR}=1) and no cached SBML at "
                f"{out_path}. Either unset {_OFFLINE_ENV_VAR}, set "
                f"model.artifact.local_sbml_path on the spec, or pre-populate the "
                f"cache: `curl -L '{source_url}' -o '{out_path}'`."
            )

        source_url = spec.model.artifact.source_url
        if source_url is None:
            source_url = (
                f"https://www.ebi.ac.uk/biomodels/model/download/{biomodels_id}"
                f"?filename={biomodels_id}_url.xml"
            )

        response = requests.get(source_url, timeout=60, verify=True)
        response.raise_for_status()

        # Sanity check: BioModels' download endpoints occasionally return the
        # web UI's HTML (with HTTP 200) instead of the SBML XML — usually
        # because the download URL changed and the old endpoint now redirects
        # to a search/landing page. Without this check, the corrupt HTML would
        # be cached as `<biomodels_id>.xml`, every DOE point would fail at
        # `roadrunner.RoadRunner(sbml_path)` with "XML content is not
        # well-formed", and the failure would only surface in
        # `sweep_logs.jsonl` — not in the immediate notebook output.
        ctype = response.headers.get("Content-Type", "").lower()
        body_head = response.content[:200].lstrip()
        looks_like_xml = body_head.startswith(b"<?xml") or body_head.startswith(b"<sbml")
        if "xml" not in ctype and not looks_like_xml:
            raise RuntimeError(
                f"BioModels download returned non-SBML content: "
                f"content-type={ctype!r}, first 80 bytes={body_head[:80]!r}. "
                f"URL: {source_url}. The BioModels download endpoint may have "
                f"changed; update `model.artifact.source_url` in your spec to "
                f"a URL that returns SBML XML."
            )

        out_path.write_bytes(response.content)
        return out_path

    def materialize_inputs(
        self, *, spec: ModelSpec, point: dict[str, float], run_dir: Path, repo_root: Path
    ) -> AdapterMaterialization:
        cache_dir = Path(spec.storage.root) / "_cache" / "biomodels"
        sbml_path = self._download_if_missing(spec=spec, cache_dir=cache_dir, repo_root=repo_root)

        parameter_payload: dict[str, float] = {}
        for mapping in spec.adapter.input_mapping:
            endpoint = mapping.to
            if endpoint is None:
                continue
            if endpoint.kind != "sbml_parameter" or endpoint.key is None:
                continue
            if mapping.var not in point:
                raise ValueError(f"Missing input variable '{mapping.var}' in design point")
            parameter_payload[endpoint.key] = float(point[mapping.var])

        worker_path = (
            repo_root / "src" / "bayesian_metamodeling" / "adapters" / "biomodels_worker.py"
        )
        # Use `sys.executable` (the running interpreter), NOT bare "python"
        # from PATH. PATH-`python` typically resolves to base conda's python
        # which lacks libroadrunner/tellurium even when the kernel env has
        # them installed; that mismatch makes every DOE point fail with
        # `ModuleNotFoundError: No module named 'roadrunner'` recorded only
        # in `sweep_logs.jsonl`. The runner (`runners/local_process.py`)
        # also substitutes `sys.executable` for bare "python" defensively;
        # we set it here too so the intent is clear at the source.
        command = [
            sys.executable,
            str(worker_path),
            "--sbml-path",
            str(sbml_path),
            "--run-dir",
            str(run_dir),
            "--params-json",
            json.dumps(parameter_payload or point),
            "--time-grid-json",
            json.dumps(
                spec.io_schema.time_grid.model_dump(mode="json") if spec.io_schema.time_grid else {}
            ),
        ]
        return AdapterMaterialization(
            command=command,
            cwd=repo_root,
            execution_env=dict(spec.runner.execution_env),
        )

    def parse_outputs(self, *, spec: ModelSpec, run_dir: Path) -> dict:
        outputs: dict = {}
        for mapping in spec.adapter.output_mapping:
            endpoint = mapping.from_
            if endpoint is None:
                continue
            if endpoint.kind == "generated" and endpoint.key == "timeseries":
                out_path = run_dir / "out" / "timeseries.json"
                outputs[mapping.var] = json.loads(out_path.read_text(encoding="utf-8"))
                continue
            raise ValueError("biomodels_sbml_adapter_v1 supports only generated/timeseries outputs")
        return outputs
