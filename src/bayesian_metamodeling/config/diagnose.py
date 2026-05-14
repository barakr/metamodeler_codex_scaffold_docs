"""System diagnostic for `bayesmm doctor`.

Pure-read: never modifies state. Returns a JSON-serializable dict that captures
OS, Python, env, package manager, optional backend availability, and a list of
plain-English recommendations.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from bayesian_metamodeling.config._import_helpers import probe_package
from bayesian_metamodeling.config.bootstrap import find_repo_root
from bayesian_metamodeling.config.platform import snapshot

_BACKEND_PACKAGES: tuple[str, ...] = ("pymc", "arviz", "torch", "sbi")


def _wheel_advisory(snap, backends: dict[str, dict[str, Any]]) -> list[str]:
    notes: list[str] = []
    py = snap.python.version_tuple
    if snap.os.is_windows and py >= (3, 13):
        for pkg in ("torch", "sbi"):
            if not backends[pkg]["installed"]:
                notes.append(
                    f"Python {snap.python.version} on Windows: prebuilt wheels for "
                    f"'{pkg}' may not yet be available. Consider Python 3.12, "
                    "or a conda install (`conda install -c conda-forge pytorch sbi`)."
                )
    if py < (3, 12):
        notes.append(
            f"Python {snap.python.version} is below the supported floor (3.12, per "
            "pyproject.toml). Upgrade your interpreter."
        )
    return notes


def _build_recommendations(
    snap, backends: dict[str, dict[str, Any]], repo_root: Path | None
) -> list[str]:
    recs: list[str] = []

    if repo_root is None:
        recs.append(
            "Could not locate the bayesian-metamodeling repo root. "
            "Run `bayesmm doctor` from inside the project directory."
        )

    if not backends["pymc"]["installed"] or not backends["arviz"]["installed"]:
        if snap.package_manager.conda_path:
            recs.append("Install PyMC backend: `conda install -c conda-forge pymc arviz`")
        recs.append("Install PyMC backend (pip): `pip install 'bayesian-metamodeling[pymc]'`")
    if not backends["torch"]["installed"] or not backends["sbi"]["installed"]:
        if snap.package_manager.conda_path:
            recs.append("Install SBI backend: `conda install -c conda-forge pytorch sbi`")
        recs.append("Install SBI backend (pip): `pip install 'bayesian-metamodeling[sbi]'`")

    recs.extend(_wheel_advisory(snap, backends))
    return recs


def diagnose() -> dict[str, Any]:
    """Build a complete environment diagnostic.

    Returns a JSON-serializable dict suitable for `mm doctor --json`. Never
    raises on missing optional dependencies.
    """
    snap = snapshot()

    backends: dict[str, dict[str, Any]] = {}
    for pkg in _BACKEND_PACKAGES:
        result = probe_package(pkg)
        backends[pkg] = {
            "installed": result.installed,
            "version": result.version,
            "import_error": result.import_error,
        }

    try:
        repo_root: Path | None = find_repo_root()
    except FileNotFoundError:
        repo_root = None

    repo_payload: dict[str, Any]
    if repo_root is None:
        repo_payload = {"root": None, "writable": False}
    else:
        repo_payload = {"root": str(repo_root), "writable": os.access(repo_root, os.W_OK)}

    return {
        "os": asdict(snap.os),
        "python": asdict(snap.python),
        "env": {
            "kind": snap.env.kind,
            "name": snap.env.name,
            "prefix": str(snap.env.prefix),
        },
        "package_manager": asdict(snap.package_manager),
        "shell": asdict(snap.shell),
        "repo": repo_payload,
        "backends": backends,
        "recommendations": _build_recommendations(snap, backends, repo_root),
    }


def format_diagnose_report(report: dict[str, Any]) -> str:
    """Render the diagnose dict as a human-readable, monospace-friendly report."""
    lines: list[str] = []
    lines.append("Bayesian Metamodeling environment diagnostic")
    lines.append("=" * 40)

    os_info = report["os"]
    lines.append(f"OS:        {os_info['system']} {os_info['release']} ({os_info['arch']})")

    py = report["python"]
    lines.append(f"Python:    {py['implementation']} {py['version']} ({py['executable']})")

    env = report["env"]
    env_label = env["kind"]
    if env["name"]:
        env_label = f"{env_label} ({env['name']})"
    lines.append(f"Env:       {env_label} -> {env['prefix']}")

    pm = report["package_manager"]
    pm_bits = [f"pip={pm['pip_version'] or 'missing'}"]
    if pm.get("conda_version"):
        pm_bits.append(f"conda={pm['conda_version']}")
    if pm.get("mamba_version"):
        pm_bits.append(f"mamba={pm['mamba_version']}")
    lines.append(f"Tools:     {', '.join(pm_bits)}")

    shell = report["shell"]
    lines.append(f"Shell:     {shell['name']} (interactive={shell['interactive']})")

    repo = report["repo"]
    lines.append(f"Repo root: {repo['root'] or 'NOT FOUND'} (writable={repo['writable']})")

    lines.append("")
    lines.append("Optional backends")
    lines.append("-" * 40)
    for pkg, info in sorted(report["backends"].items()):
        if info["installed"]:
            lines.append(f"  [OK]   {pkg:8s} {info['version'] or '(version unknown)'}")
        else:
            err = info["import_error"] or "not installed"
            lines.append(f"  [MISS] {pkg:8s} {err}")

    recs: list[str] = report["recommendations"]
    if recs:
        lines.append("")
        lines.append("Recommendations")
        lines.append("-" * 40)
        for rec in recs:
            lines.append(f"  - {rec}")

    return "\n".join(lines) + "\n"


def diagnose_to_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True)
