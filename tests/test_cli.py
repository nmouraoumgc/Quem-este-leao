from __future__ import annotations

from typer.testing import CliRunner

from quem_e_este_leao.cli import app


runner = CliRunner()


def test_help_lists_new_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    out = result.stdout
    for cmd in ("generate", "preview", "publish", "reveal", "players", "reset", "status"):
        assert cmd in out


def test_preview_is_generate_alias() -> None:
    result = runner.invoke(app, ["preview", "--help"])
    assert result.exit_code == 0
    assert "dry-run" in result.stdout.lower() or "pré-visualização" in result.stdout.lower()
