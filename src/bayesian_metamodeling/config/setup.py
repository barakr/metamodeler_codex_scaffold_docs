"""Configurer for `bayesmm setup`.

Detects the user's platform and prints the OS-correct install commands for the
backends they want. Advisory only: it never installs anything and never writes
state — fits stay fully determined by the SurrogateSpec.

In `interactive=True` mode it prompts via `input()` for the backend list. In
`interactive=False` mode the backend list comes from arguments — suitable for
scripting and tests.
"""

from __future__ import annotations

from typing import Any

from bayesian_metamodeling.config.platform import PlatformSnapshot, snapshot

_VALID_BACKENDS: frozenset[str] = frozenset({"pymc", "sbi"})


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
    target = "bayesian-metamodeling" + (f"[{extras}]" if extras else "")
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


def _prompt_backends() -> list[str]:
    try:
        raw = input(
            "Which optional backends do you want?\n"
            "  Choices: pymc, sbi, pymc,sbi, none [default: pymc,sbi]: "
        ).strip()
    except EOFError:
        # Non-interactive stdin (piped / CI): fall back to the default set.
        return ["pymc", "sbi"]
    if not raw:
        return ["pymc", "sbi"]
    return _normalize_backends(raw)


def setup(
    *,
    interactive: bool = True,
    install_backends: list[str] | str | None = None,
) -> dict[str, Any]:
    """Run the configurer.

    Detects the platform and prints OS-correct install commands for the chosen
    backends. Returns a dict with the chosen backends and the generated
    commands. Never executes installs and never writes files.
    """
    snap = snapshot()

    backends = _normalize_backends(install_backends)
    if interactive and not backends:
        backends = _prompt_backends()

    commands = format_install_commands(snap, backends)

    print("Suggested install commands (review and run yourself):")
    for cmd in commands:
        print(f"  {cmd}")

    print("\nNext steps:")
    print("  1) Run the install command above.")
    print("  2) Run `bayesmm doctor` to verify the backends are present.")
    print("  3) Try a tutorial: `jupyter execute tutorials/Tutorial_1.ipynb`.")

    return {
        "backends": backends,
        "install_commands": commands,
    }
