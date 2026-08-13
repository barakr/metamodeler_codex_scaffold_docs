"""Environment configuration, diagnostics, and bootstrap helpers."""

from __future__ import annotations

from bayesian_metamodeling.config.bootstrap import bootstrap, find_repo_root
from bayesian_metamodeling.config.diagnose import diagnose, format_diagnose_report

# Module named `install_advice`, not `setup`: GitHub's dependency graph reads any file
# called setup.py as a pip manifest, and this one is a CLI helper that merely *mentions*
# package names in its install advice. That put phantom dependencies into the graph the
# repository relies on for vulnerability alerts. The public name is unchanged.
from bayesian_metamodeling.config.install_advice import format_install_commands, setup

__all__ = [
    "bootstrap",
    "diagnose",
    "find_repo_root",
    "format_diagnose_report",
    "format_install_commands",
    "setup",
]
