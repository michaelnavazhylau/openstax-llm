from __future__ import annotations

from openstax_llm.cli import main


def test_cli_version(capsys) -> None:
    try:
        main(["--version"])
    except SystemExit as exc:
        assert exc.code == 0
    captured = capsys.readouterr()
    assert "openstax-llm" in captured.out


def test_cli_no_args_shows_help(capsys) -> None:
    assert main([]) == 0
    captured = capsys.readouterr()
    assert "openstax-llm" in captured.out


def test_cli_search(capsys) -> None:
    assert main(["search", "python"]) == 0
    captured = capsys.readouterr()
    assert "introduction-python-programming" in captured.out
