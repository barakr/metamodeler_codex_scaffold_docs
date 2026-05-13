"""Cross-platform OS, shell, env, and package-manager detection.

Pure-read helpers — never write or execute installs. Used by `diagnose()`
to assemble a complete picture, and by `setup()` to generate the right
install commands per platform.
"""

from __future__ import annotations

import importlib.metadata
import os
import platform as _platform
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class OSInfo:
    system: str  # "Windows" | "Darwin" | "Linux"
    release: str
    arch: str
    is_windows: bool
    is_macos: bool
    is_linux: bool


@dataclass
class PythonInfo:
    version: str
    implementation: str
    executable: str
    version_tuple: tuple[int, int, int]


@dataclass
class EnvInfo:
    kind: str  # "conda" | "venv" | "system"
    name: str | None
    prefix: Path


@dataclass
class PackageManagerInfo:
    pip_version: str | None
    conda_path: str | None
    conda_version: str | None
    mamba_path: str | None
    mamba_version: str | None


@dataclass
class ShellInfo:
    name: str  # "cmd" | "powershell" | "pwsh" | "bash" | "zsh" | "sh" | "unknown"
    interactive: bool


@dataclass
class PlatformSnapshot:
    os: OSInfo
    python: PythonInfo
    env: EnvInfo
    package_manager: PackageManagerInfo
    shell: ShellInfo
    extras: dict[str, str] = field(default_factory=dict)


def detect_os() -> OSInfo:
    system = _platform.system()
    return OSInfo(
        system=system,
        release=_platform.release(),
        arch=_platform.machine(),
        is_windows=system == "Windows",
        is_macos=system == "Darwin",
        is_linux=system == "Linux",
    )


def detect_python() -> PythonInfo:
    info = sys.version_info
    return PythonInfo(
        version=_platform.python_version(),
        implementation=_platform.python_implementation(),
        executable=sys.executable,
        version_tuple=(info.major, info.minor, info.micro),
    )


def detect_env() -> EnvInfo:
    conda_prefix = os.environ.get("CONDA_PREFIX")
    conda_name = os.environ.get("CONDA_DEFAULT_ENV")
    if conda_prefix:
        return EnvInfo(
            kind="conda",
            name=conda_name or Path(conda_prefix).name,
            prefix=Path(conda_prefix),
        )

    # `conda-meta/` is the marker of a conda env even when CONDA_PREFIX isn't set
    # (e.g. running the env's interpreter directly from a non-activated shell).
    if (Path(sys.prefix) / "conda-meta").is_dir():
        return EnvInfo(kind="conda", name=Path(sys.prefix).name, prefix=Path(sys.prefix))

    venv_prefix = os.environ.get("VIRTUAL_ENV")
    if venv_prefix:
        return EnvInfo(kind="venv", name=Path(venv_prefix).name, prefix=Path(venv_prefix))

    if sys.prefix != sys.base_prefix:
        return EnvInfo(kind="venv", name=Path(sys.prefix).name, prefix=Path(sys.prefix))

    return EnvInfo(kind="system", name=None, prefix=Path(sys.prefix))


def _tool_version(executable: str, args: list[str]) -> str | None:
    path = shutil.which(executable)
    if not path:
        return None
    try:
        result = subprocess.run(
            [path, *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = (result.stdout or result.stderr or "").strip().splitlines()
    return output[0] if output else None


def detect_package_manager() -> PackageManagerInfo:
    try:
        pip_version: str | None = importlib.metadata.version("pip")
    except importlib.metadata.PackageNotFoundError:
        pip_version = None

    conda_path = shutil.which("conda")
    mamba_path = shutil.which("mamba")
    return PackageManagerInfo(
        pip_version=pip_version,
        conda_path=conda_path,
        conda_version=_tool_version("conda", ["--version"]) if conda_path else None,
        mamba_path=mamba_path,
        mamba_version=_tool_version("mamba", ["--version"]) if mamba_path else None,
    )


def detect_shell() -> ShellInfo:
    if os.environ.get("PSMODULEPATH"):
        return ShellInfo(
            name="powershell" if os.name == "nt" else "pwsh", interactive=sys.stdin.isatty()
        )
    comspec = os.environ.get("COMSPEC", "")
    if os.name == "nt" and comspec.lower().endswith("cmd.exe"):
        return ShellInfo(name="cmd", interactive=sys.stdin.isatty())
    shell = os.environ.get("SHELL", "")
    name = Path(shell).name if shell else "unknown"
    if name in {"bash", "zsh", "sh", "fish"}:
        return ShellInfo(name=name, interactive=sys.stdin.isatty())
    return ShellInfo(name=name or "unknown", interactive=sys.stdin.isatty())


def snapshot() -> PlatformSnapshot:
    return PlatformSnapshot(
        os=detect_os(),
        python=detect_python(),
        env=detect_env(),
        package_manager=detect_package_manager(),
        shell=detect_shell(),
    )
