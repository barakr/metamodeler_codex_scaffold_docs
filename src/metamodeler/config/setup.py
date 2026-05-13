"""Configurer for `mm setup`.

Generates platform-correct install commands for the user's chosen backends and
optionally writes a project-local config file (`metamodeler.config.json`) with
default backend settings (e.g. `output_correlation`, `density_estimator`).

In `interactive=True` mode, prompts via `input()`. In `interactive=False`
mode, all choices come from arguments — suitable for scripting and tests.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from metamodeler.config.bootstrap import find_repo_root
from metamodeler.config.platform import PlatformSnapshot, snapshot

_VALID_BACKENDS: frozenset[str] = frozenset({"pymc", "sbi"})

_DEFAULT_CONFIG: dict[str, Any] = {
    "schema_version": "1.0",
    "defaults": {
        "pymc_gp": {
            "output_correlation": "diagonal",
            "draws": 300,
            "tune": 300,
            "chains": 1,
            "target_accept": 0.9,
        },
        "sbi_npe": {
            "output_correlation": "diagonal",
            "density_estimator": "maf",
            "max_num_epochs": 120,
            "training_batch_size": 32,
        },
    },
}


def _normalize_backends(backends: list[str] | str | None) -> list[str]:
    if backends is None:
        return []
    if isinstance(backends, str):
        items = [item.strip() for item in backends.split(",") if item.strip()]
    else:
        items = [str(item).strip() for item in backends if str(item).strip()]
    out: list[str] = []
    for item in items:
        low = item.lower()
        if low == "none":
            return []
        if low not in _VALID_BACKENDS:
            raise ValueError(
                f"Unknown backend '{item}'. Valid choices: {sorted(_VALID_BACKENDS)} or 'none'."
            )
        if low not in out:
            out.append(low)
    return out


def _pip_command(snap: PlatformSnapshot, backends: list[str]) -> str:
    extras = ",".join(backends) if backends else ""
    target = "metamodeler" + (f"[{extras}]" if extras else "")
    quote = '"' if snap.os.is_windows else "'"
    extras_suffix = f"[{extras}]" if extras else ""
    editable = f"pip install -e {quote}.{extras_suffix}{quote}"
    direct = f"pip install {quote}{target}{quote}"
    return f"{editable}  # or: {direct}"


def _conda_command(snap: PlatformSnapshot, backends: list[str]) -> str | None:
    if not snap.package_manager.conda_path:
        return None
    parts: list[str] = []
    if "pymc" in backends:
        parts.extend(["pymc", "arviz"])
    if "sbi" in backends:
        parts.extend(["pytorch", "sbi"])
    if not parts:
        return None
    env_arg = ""
    if snap.env.kind == "conda" and snap.env.name:
        env_arg = f"-n {snap.env.name} "
    return f"conda install {env_arg}-c conda-forge {' '.join(parts)}"


def format_install_commands(snap: PlatformSnapshot, backends: list[str]) -> list[str]:
    commands: list[str] = []
    conda_cmd = _conda_command(snap, backends)
    if conda_cmd:
        commands.append(f"# (conda) {conda_cmd}")
    commands.append(f"# (pip)   {_pip_command(snap, backends)}")
    return commands


def _prompt_yes_no(question: str, default: bool = True) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    raw = input(f"{question} {suffix} ").strip().lower()
    if not raw:
        return default
    return raw in {"y", "yes"}


def _prompt_backends() -> list[str]:
    raw = input(
        "Which optional backends do you want?\n"
        "  Choices: pymc, sbi, pymc,sbi, none [default: pymc,sbi]: "
    ).strip()
    if not raw:
        return ["pymc", "sbi"]
    return _normalize_backends(raw)


def _write_config(repo_root: Path, backends: list[str]) -> Path:
    config_path = repo_root / "metamodeler.config.json"
    payload = json.loads(json.dumps(_DEFAULT_CONFIG))
    payload["selected_backends"] = backends
    config_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return config_path


def setup(
    *,
    interactive: bool = True,
    install_backends: list[str] | str | None = None,
    write_config: bool = True,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Run the configurer.

    Returns a dict with the chosen backends, the install commands generated,
    and the path to the written config (if any). Never executes installs;
    prints them so the user can review and run themselves.
    """
    snap = snapshot()
    if repo_root is None:
        try:
            repo_root = find_repo_root()
        except FileNotFoundError:
            repo_root = None

    backends = _normalize_backends(install_backends)
    if interactive:
        if not backends:
            backends = _prompt_backends()
        if write_config and not _prompt_yes_no(
            "Write metamodeler.config.json with default backend settings?", default=True
        ):
            write_config = False

    commands = format_install_commands(snap, backends)

    print("Suggested install commands (review and run yourself):")
    for cmd in commands:
        print(f"  {cmd}")

    config_path: Path | None = None
    if write_config and repo_root is not None:
        config_path = _write_config(repo_root, backends)
        print(f"\nWrote default config: {config_path}")
    elif write_config and repo_root is None:
        print("\nSkipped config write: no repo root detected.")

    print("\nNext steps:")
    print("  1) Run the install command above (or `mm doctor` to confirm what's missing).")
    print("  2) Re-run `mm doctor` to verify backends are present.")
    print("  3) Try a tutorial: `jupyter execute tutorials/Tutorial_1.ipynb`.")

    return {
        "backends": backends,
        "install_commands": commands,
        "config_path": str(config_path) if config_path else None,
        "repo_root": str(repo_root) if repo_root else None,
    }
