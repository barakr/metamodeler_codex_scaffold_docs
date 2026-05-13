"""Environment configuration, diagnostics, and bootstrap helpers."""

from __future__ import annotations

from bayesian_metamodeling.config.bootstrap import bootstrap, find_repo_root
from bayesian_metamodeling.config.diagnose import diagnose, format_diagnose_report
from bayesian_metamodeling.config.setup import format_install_commands, setup

__all__ = [
    "bootstrap",
    "diagnose",
    "find_repo_root",
    "format_diagnose_report",
    "format_install_commands",
    "setup",
]
