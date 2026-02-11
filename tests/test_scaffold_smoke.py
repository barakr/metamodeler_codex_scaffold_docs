import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from metamodeler.cli.main import main


def test_main_help_runs(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["mm"])
    code = main()
    out = capsys.readouterr().out

    assert code == 0
    assert "Metamodeler CLI (scaffold)" in out
