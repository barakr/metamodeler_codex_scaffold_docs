"""Security hardening tests for path traversal, input validation, and deserialization guards."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from bayesian_metamodeling.adapters.python_cli import PythonCLIAdapter
from bayesian_metamodeling.spec import load_and_validate_modelspec
from bayesian_metamodeling.surrogates.dataset import _resolve_dataset_root


def _minimal_spec_payload(**overrides) -> dict:
    base = {
        "schema_version": "1.0",
        "model": {
            "name": "test",
            "version": "0.1.0",
            "artifact": {"type": "local", "entrypoint": ["python", "run.py"]},
        },
        "runner": {
            "mode": "local_process",
            "resources": {"cpus": 1, "mem_gb": 1, "walltime_min": 1},
        },
        "io_schema": {
            "inputs": [{"name": "x", "type": "float", "units": "m", "support": [0.0, 1.0]}],
            "outputs": [{"name": "y", "type": "float", "units": "m"}],
        },
        "design": {"strategy": "grid", "grid": {"x": [0.0, 0.5, 1.0]}},
        "adapter": {
            "id": "python_cli_adapter_v1",
            "input_mapping": [{"var": "x", "to": {"kind": "cli_arg", "key": "--x"}}],
            "output_mapping": [{"var": "y", "from": {"kind": "file", "path": "out.json"}}],
        },
        "reproducibility": {"seed": 42},
        "storage": {"root": "tmp/test_store"},
    }
    for key, val in overrides.items():
        keys = key.split(".")
        target = base
        for k in keys[:-1]:
            target = target[k]
        target[keys[-1]] = val
    return base


# --- Path traversal in output mapping (H2) ---


class TestOutputPathTraversal:
    def test_rejects_path_traversal_in_output_mapping(self, tmp_path):
        adapter = PythonCLIAdapter()
        run_dir = tmp_path / "run"
        run_dir.mkdir()

        spec_payload = _minimal_spec_payload()
        spec_payload["adapter"]["output_mapping"] = [
            {"var": "y", "from": {"kind": "file", "path": "../../etc/passwd"}}
        ]
        spec = load_and_validate_modelspec(spec_payload)

        with pytest.raises(ValueError, match="Path traversal detected"):
            adapter.parse_outputs(spec=spec, run_dir=run_dir)

    def test_accepts_normal_output_path(self, tmp_path):
        adapter = PythonCLIAdapter()
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        out_file = run_dir / "out.json"
        out_file.write_text(json.dumps({"value": 1.0}))

        spec_payload = _minimal_spec_payload()
        spec = load_and_validate_modelspec(spec_payload)
        result = adapter.parse_outputs(spec=spec, run_dir=run_dir)
        assert "y" in result


# --- Entrypoint path check: a TYPO check, not a containment boundary (H1) ---


class TestEntrypointPathTypoCheck:
    """Renamed and re-scoped deliberately (S2b).

    This check cannot contain a spec — `entrypoint` names the command to execute, so a
    spec is trusted input by design (README, "Specs are trusted input"). It catches
    "I pointed at the wrong directory", which is a real mistake worth catching. The
    assertion message below changed with the relabelling; the behaviour did not.

    The check now also inspects **every** path-like argument rather than only
    `command[1]`, and recognises `\\` as well as `/` — previously any Windows-style path
    skipped it entirely.
    """

    def test_rejects_entrypoint_outside_repo(self, tmp_path):
        adapter = PythonCLIAdapter()
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        run_dir = tmp_path / "run"
        run_dir.mkdir()

        spec_payload = _minimal_spec_payload()
        spec_payload["model"]["artifact"]["entrypoint"] = [
            "python",
            "/etc/evil_script.py",
        ]
        spec = load_and_validate_modelspec(spec_payload)

        with pytest.raises(ValueError, match="points outside the repository"):
            adapter.materialize_inputs(
                spec=spec, point={"x": 0.5}, run_dir=run_dir, repo_root=repo_root
            )

    def test_windows_separator_no_longer_skips_the_check(self, tmp_path):
        """The old guard tested only "/", so `..\\..\\x.py` was never inspected."""
        adapter = PythonCLIAdapter()
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        run_dir = tmp_path / "run"
        run_dir.mkdir()

        spec_payload = _minimal_spec_payload()
        spec_payload["model"]["artifact"]["entrypoint"] = ["python", "..\\..\\outside.py"]
        spec = load_and_validate_modelspec(spec_payload)

        with pytest.raises(ValueError, match="points outside the repository"):
            adapter.materialize_inputs(
                spec=spec, point={"x": 0.5}, run_dir=run_dir, repo_root=repo_root
            )

    def test_checks_arguments_beyond_the_second(self, tmp_path):
        """The old guard inspected `command[1]` only."""
        adapter = PythonCLIAdapter()
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        run_dir = tmp_path / "run"
        run_dir.mkdir()

        spec_payload = _minimal_spec_payload()
        spec_payload["model"]["artifact"]["entrypoint"] = [
            "python",
            "runner.py",
            "--script",
            "/etc/elsewhere.py",
        ]
        spec = load_and_validate_modelspec(spec_payload)

        with pytest.raises(ValueError, match="points outside the repository"):
            adapter.materialize_inputs(
                spec=spec, point={"x": 0.5}, run_dir=run_dir, repo_root=repo_root
            )

    def test_accepts_relative_entrypoint(self, tmp_path):
        adapter = PythonCLIAdapter()
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        run_dir = tmp_path / "run"
        run_dir.mkdir()

        spec_payload = _minimal_spec_payload()
        spec = load_and_validate_modelspec(spec_payload)
        result = adapter.materialize_inputs(
            spec=spec, point={"x": 0.5}, run_dir=run_dir, repo_root=repo_root
        )
        assert "run.py" in result.command


# --- conda_env validation (H4) ---


class TestCondaEnvValidation:
    @pytest.mark.parametrize(
        "bad_name",
        [
            "; rm -rf /",
            "env && evil",
            "../escape",
            "",
            " ",
            "-startswithdash",
        ],
    )
    def test_rejects_invalid_conda_env_names(self, bad_name):
        payload = _minimal_spec_payload()
        payload["runner"]["execution_env"] = {"conda_env": bad_name}
        with pytest.raises(ValidationError):
            load_and_validate_modelspec(payload)

    @pytest.mark.parametrize(
        "good_name",
        [
            "py314_bayesmm",
            "my.env",
            "env-name",
            "env_name",
        ],
    )
    def test_accepts_valid_conda_env_names(self, good_name):
        payload = _minimal_spec_payload()
        payload["runner"]["execution_env"] = {"conda_env": good_name}
        spec = load_and_validate_modelspec(payload)
        assert spec.runner.execution_env["conda_env"] == good_name


# --- storage.root traversal guard (L1) ---


class TestStorageRootTraversal:
    def test_rejects_storage_root_with_traversal(self):
        payload = _minimal_spec_payload()
        payload["storage"]["root"] = "../outside_project/data"
        with pytest.raises(ValidationError, match="traversal"):
            load_and_validate_modelspec(payload)

    def test_rejects_absolute_storage_root(self):
        payload = _minimal_spec_payload()
        payload["storage"]["root"] = "/tmp/absolute"
        with pytest.raises(ValidationError, match="project-relative"):
            load_and_validate_modelspec(payload)

    def test_accepts_normal_storage_root(self):
        payload = _minimal_spec_payload()
        payload["storage"]["root"] = "tmp/test_store"
        spec = load_and_validate_modelspec(payload)
        assert spec.storage.root == "tmp/test_store"


# --- Trust-boundary visibility: show the command before running it (S2d) ---


class TestEntrypointConfirmation:
    """Visibility, not containment.

    Running a spec runs its author's code — that is the composition mechanism. These
    tests pin that the command is *shown*, that leaving the repository *asks*, and that
    a suppressed prompt still says so. The last one matters most: a silenced prompt that
    looked identical to no prompt would be the same class of defect this codebase keeps
    finding in its own CI.
    """

    @staticmethod
    def _spec(entrypoint):
        payload = _minimal_spec_payload()
        payload["model"]["artifact"] = {"type": "local", "entrypoint": entrypoint}
        return load_and_validate_modelspec(payload)

    def test_prints_the_command_and_does_not_prompt_inside_the_repo(self, capsys):
        from bayesian_metamodeling.cli.main import _confirm_entrypoint

        assert _confirm_entrypoint(self._spec(["python", "models/toy.py"]), assume_yes=False)
        assert "Entrypoint: python models/toy.py" in capsys.readouterr().out

    def test_refuses_non_interactively_when_entrypoint_leaves_the_repo(self, capsys, monkeypatch):
        from bayesian_metamodeling.cli import main as cli_main

        monkeypatch.setattr(cli_main.sys.stdin, "isatty", lambda: False, raising=False)
        assert not cli_main._confirm_entrypoint(
            self._spec(["python", "../../../outside.py"]), assume_yes=False
        )
        assert "Refusing to run non-interactively" in capsys.readouterr().out

    def test_assume_yes_proceeds_but_says_that_it_did(self, capsys):
        from bayesian_metamodeling.cli.main import _confirm_entrypoint

        assert _confirm_entrypoint(self._spec(["python", "../../../outside.py"]), assume_yes=True)
        out = capsys.readouterr().out
        assert "points outside the repository" in out
        assert "Proceeding without confirmation" in out, (
            "a suppressed prompt must be visible in the output, or it is "
            "indistinguishable from no prompt at all"
        )

    def test_biomodels_specs_have_no_user_entrypoint_to_confirm(self):
        from bayesian_metamodeling.cli.main import _confirm_entrypoint

        payload = _minimal_spec_payload()
        payload["model"]["artifact"] = {"type": "biomodels", "biomodels_id": "BIOMD0000000001"}
        assert _confirm_entrypoint(load_and_validate_modelspec(payload), assume_yes=False)


# --- Path-safe spec fields that become directory/file names (S3) ---


class TestPathSafeSegments:
    """`model.name` and `biomodels_id` are interpolated into paths.

    `model.name` is the serious one: `cli/main.py` builds
    `<storage.root>/_active/<token>/<name>_<i>` and `shutil.rmtree`s it in a
    `finally`, so an unvalidated name puts a recursive delete on a path the spec
    author chose. The realistic failure is an accident (`lck/activity`), not an
    attack — a spec already names the command to run, so a hostile spec has no
    need of this.
    """

    @pytest.mark.parametrize(
        "bad_name",
        ["../../evil", "lck/activity", "back\\slash", "a b", ".hidden", "-leading-dash"],
    )
    def test_rejects_unsafe_model_name(self, bad_name):
        payload = _minimal_spec_payload()
        payload["model"]["name"] = bad_name
        with pytest.raises(ValidationError, match="model.name"):
            load_and_validate_modelspec(payload)

    @pytest.mark.parametrize("good_name", ["toy_program", "lck_activity", "model-2", "v1.2"])
    def test_accepts_normal_model_name(self, good_name):
        payload = _minimal_spec_payload()
        payload["model"]["name"] = good_name
        assert load_and_validate_modelspec(payload).model.name == good_name

    def test_rejects_traversal_in_biomodels_id(self):
        payload = _minimal_spec_payload()
        payload["model"]["artifact"] = {
            "type": "biomodels",
            "biomodels_id": "../../../etc/passwd",
        }
        with pytest.raises(ValidationError, match="biomodels_id"):
            load_and_validate_modelspec(payload)

    def test_accepts_real_biomodels_id(self):
        payload = _minimal_spec_payload()
        payload["model"]["artifact"] = {"type": "biomodels", "biomodels_id": "BIOMD0000000001"}
        spec = load_and_validate_modelspec(payload)
        assert spec.model.artifact.biomodels_id == "BIOMD0000000001"

    @pytest.mark.parametrize("bad_path", ["../../../etc/passwd", "/etc/passwd", "..\\win"])
    def test_rejects_escaping_local_sbml_path(self, bad_path):
        payload = _minimal_spec_payload()
        payload["model"]["artifact"] = {
            "type": "biomodels",
            "biomodels_id": "BIOMD0000000001",
            "local_sbml_path": bad_path,
        }
        with pytest.raises(ValidationError, match="local_sbml_path"):
            load_and_validate_modelspec(payload)

    def test_accepts_in_tree_local_sbml_path(self):
        payload = _minimal_spec_payload()
        payload["model"]["artifact"] = {
            "type": "biomodels",
            "biomodels_id": "BIOMD0000000001",
            "local_sbml_path": "tutorials/data/sample.xml",
        }
        spec = load_and_validate_modelspec(payload)
        assert spec.model.artifact.local_sbml_path == "tutorials/data/sample.xml"


# --- Dataset path validation (M1) ---


class TestDatasetPathValidation:
    def test_rejects_traversal_in_dataset_path(self):
        with pytest.raises(ValueError, match="traversal"):
            _resolve_dataset_root("../outside/data")

    def test_rejects_traversal_in_dataset_dict(self):
        with pytest.raises(ValueError, match="traversal"):
            _resolve_dataset_root({"run_store_root": "../escape"})

    def test_accepts_normal_dataset_path(self):
        result = _resolve_dataset_root("tmp/test_store")
        assert result == Path("tmp/test_store")

    def test_accepts_absolute_dataset_path(self):
        result = _resolve_dataset_root("/tmp/test_store")
        assert result == Path("/tmp/test_store")


# --- Surrogate registry containment (S4a) ---


class TestSurrogateRegistryContainment:
    """The registry is a plain JSON file, and the payload it names can reach `torch.load`.

    `run_store.show_registered_run` has always refused entries pointing outside the
    project; this path did not. Anchored on the registry's own directory rather than the
    process cwd, because that is the invariant `persist_surrogate_artifact` actually
    maintains — and because a rule that depends on where you launched `bayesmm` from is
    the cwd-sensitivity recorded as D3.
    """

    def test_rejects_entry_pointing_outside_the_store(self, tmp_path, monkeypatch):
        from bayesian_metamodeling.storage import surrogate_store

        registry = tmp_path / "store" / "surrogate_registry.json"
        registry.parent.mkdir(parents=True)
        elsewhere = tmp_path / "elsewhere" / "artifact.json"
        elsewhere.parent.mkdir(parents=True)
        elsewhere.write_text(json.dumps({"artifact_id": "x", "spec_name": "s"}))
        registry.write_text(json.dumps({"x": str(elsewhere)}))
        monkeypatch.setattr(surrogate_store, "SURROGATE_REGISTRY_PATH", registry)

        with pytest.raises(ValueError, match="outside the surrogate store"):
            surrogate_store.find_latest_artifact_for_spec("s")

    def test_persist_and_lookup_agree_on_the_store_root(self, tmp_path, monkeypatch):
        """The bug this pins: the registry path was overridable, the artifact dir was not.

        `persist_surrogate_artifact` hardcoded `tmp/surrogate_artifacts`, so relocating
        the registry put the two in different roots — which only became visible once
        something checked.
        """
        from bayesian_metamodeling.spec import SurrogateSpec
        from bayesian_metamodeling.storage import surrogate_store

        registry = tmp_path / "store" / "surrogate_registry.json"
        registry.parent.mkdir(parents=True)
        monkeypatch.setattr(surrogate_store, "SURROGATE_REGISTRY_PATH", registry)

        payload = tmp_path / "payload.json"
        payload.write_text(json.dumps({"model_type": "pymc_bayesian_linear_v2"}))
        spec = SurrogateSpec.model_validate(
            {
                "schema_version": "1.0",
                "name": "roundtrip",
                "kind": "conditional",
                "backend": "pymc_gp",
                "dataset_ref": {"run_store_root": "tmp/store"},
                "inputs": ["a"],
                "outputs": ["y"],
                "seed": 0,
            }
        )
        surrogate_store.persist_surrogate_artifact(
            spec=spec, dataset_digest="d", payload_path=payload
        )

        _, found = surrogate_store.find_latest_artifact_for_spec("roundtrip")
        assert found.resolve().is_relative_to(registry.parent.resolve())


# --- torch deserialization: a CORRUPTION check, not a security control (C1) ---


class TestTorchDeserializationCorruptionCheck:
    """This class used to be named as though it tested a security control. It does not.

    `_deserialize_torch_object` calls `torch.load(..., weights_only=False)`, which is
    pickle. Pickle executes code **while deserialising** — a crafted payload runs inside
    `torch.load`, on the line *before* the `hasattr(obj, "sample")` check. The check
    therefore inspects the return value of an operation whose danger is its side effects,
    and cannot stop a malicious artifact. It can only catch a *corrupted* or
    wrong-type one, which is worth having and is what these tests actually pin.

    Naming it a security test was worse than having no test: a reader saw a green
    assertion and concluded the deserialisation path was defended. The real fix is to
    stop pickling (see REVIEW_AND_UPGRADE_PLAN.md, S1a); until that lands, this test
    says what it means.
    """

    def test_rejects_object_without_posterior_interface(self, monkeypatch):
        import bayesian_metamodeling.surrogates.backends as backends_mod

        monkeypatch.delenv(backends_mod.STRICT_ARTIFACTS_ENV_VAR, raising=False)

        fake_torch = MagicMock()
        fake_torch.load.return_value = {"not": "a posterior"}
        monkeypatch.setattr(backends_mod, "_require_torch", lambda: fake_torch)

        import base64
        import io

        buffer = io.BytesIO(b"fake_data")
        serialized = base64.b64encode(buffer.getvalue()).decode("ascii")

        # The legacy path also announces itself now (S1a): it warns that the artifact is
        # executable and names the fix. Asserting that here means the announcement cannot
        # quietly disappear.
        with (
            pytest.warns(backends_mod.LegacyPickleArtifactWarning, match="runs code contained"),
            pytest.raises(ValueError, match="does not implement the expected posterior"),
        ):
            backends_mod._deserialize_torch_object(serialized)

    def test_accepts_object_with_posterior_interface(self, monkeypatch):
        import bayesian_metamodeling.surrogates.backends as backends_mod

        monkeypatch.delenv(backends_mod.STRICT_ARTIFACTS_ENV_VAR, raising=False)

        mock_posterior = MagicMock()
        mock_posterior.sample = MagicMock()
        mock_posterior.log_prob = MagicMock()

        fake_torch = MagicMock()
        fake_torch.load.return_value = mock_posterior
        monkeypatch.setattr(backends_mod, "_require_torch", lambda: fake_torch)

        import base64
        import io

        buffer = io.BytesIO(b"fake_data")
        serialized = base64.b64encode(buffer.getvalue()).decode("ascii")

        with pytest.warns(backends_mod.LegacyPickleArtifactWarning):
            result = backends_mod._deserialize_torch_object(serialized)
        assert result is mock_posterior
