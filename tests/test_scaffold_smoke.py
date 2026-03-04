from bayesian_metamodeling.cli.main import main


def test_main_help_runs(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["mm"])
    code = main()
    out = capsys.readouterr().out

    assert code == 0
    assert "Bayesian Metamodeling CLI" in out
