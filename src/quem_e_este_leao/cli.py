"""CLI: generate, publish, reveal, run-once, serve-scheduler, reveal-due."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from quem_e_este_leao.config import Difficulty, RevealDelay, Settings, load_settings
from quem_e_este_leao.logging_setup import setup_logging

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Quem É Este Leão? — quiz visual #SpacesSporting (pt-PT).",
)


def _settings(
    difficulty: Optional[str] = None,
    reveal_delay: Optional[str] = None,
    dry_run: Optional[bool] = None,
) -> Settings:
    overrides: dict = {}
    if difficulty:
        overrides["difficulty"] = Difficulty(difficulty)
    if reveal_delay:
        overrides["reveal_delay"] = RevealDelay(reveal_delay)
    if dry_run is not None:
        overrides["dry_run"] = dry_run
    settings = load_settings(**overrides)
    setup_logging(settings.log_level)
    return settings


@app.command()
def generate(
    difficulty: str = typer.Option("medium", "--difficulty", "-d", help="easy | medium | hard"),
    reveal_in: str = typer.Option("1h", "--reveal-in", help="30min | 1h | 3h"),
    output_dir: Optional[Path] = typer.Option(None, "--output-dir", "-o"),
    player_id: Optional[str] = typer.Option(None, "--player-id", hidden=True),
    dry_run: bool = typer.Option(True, "--dry-run/--no-dry-run"),
) -> None:
    """Gera um quiz (imagem + legenda) em rascunho. Não revela o nome."""
    from quem_e_este_leao.players import get_player, load_players
    from quem_e_este_leao.quiz import generate_quiz

    settings = _settings(difficulty, reveal_in, dry_run)
    out = output_dir or settings.preview_dir
    chosen = None
    if player_id:
        chosen = get_player(load_players(settings.players_yaml), player_id)
    quiz = generate_quiz(
        settings,
        difficulty=Difficulty(difficulty),
        reveal_delay=RevealDelay(reveal_in),
        output_dir=out,
        player=chosen,
    )
    typer.echo(f"Quiz gerado: {quiz.quiz_id}")
    typer.echo(f"Imagem: {quiz.processed_image}")
    typer.echo("Legenda:")
    typer.echo(quiz.caption)


@app.command()
def publish(
    quiz_id: Optional[str] = typer.Option(None, "--quiz-id"),
    dry_run: bool = typer.Option(True, "--dry-run/--no-dry-run"),
) -> None:
    """Publica um rascunho (local por omissão; X se houver credenciais)."""
    from quem_e_este_leao import db
    from quem_e_este_leao.publish import get_publisher

    settings = _settings(dry_run=dry_run)
    with db.session(settings.database_path) as conn:
        row = db.get_quiz(conn, quiz_id) if quiz_id else db.latest_draft(conn)
        if row is None:
            raise typer.BadParameter("Não há rascunho para publicar.")
        qid = row["id"]
    remote = get_publisher(settings).publish_quiz(qid)
    typer.echo(f"Publicado {qid}" + (f" → {remote}" if remote else ""))


@app.command()
def reveal(
    quiz_id: str = typer.Option(..., "--quiz-id"),
    dry_run: bool = typer.Option(True, "--dry-run/--no-dry-run"),
) -> None:
    """Publica a revelação de um quiz."""
    from quem_e_este_leao.publish import get_publisher

    settings = _settings(dry_run=dry_run)
    remote = get_publisher(settings).publish_reveal(quiz_id)
    typer.echo(f"Revelado {quiz_id}" + (f" → {remote}" if remote else ""))


@app.command("reveal-due")
def reveal_due_cmd(
    dry_run: bool = typer.Option(True, "--dry-run/--no-dry-run"),
) -> None:
    """Revela quizzes cuja hora já passou (pensado para cron)."""
    from quem_e_este_leao.schedule import reveal_due

    settings = _settings(dry_run=dry_run)
    ids = reveal_due(settings)
    if ids:
        typer.echo("Revelados: " + ", ".join(ids))
    else:
        typer.echo("Nada a revelar.")


@app.command("run-once")
def run_once(
    difficulty: str = typer.Option("medium", "--difficulty", "-d"),
    reveal_in: str = typer.Option("1h", "--reveal-in"),
    dry_run: bool = typer.Option(True, "--dry-run/--no-dry-run"),
) -> None:
    """Gera e publica um quiz de imediato (ciclo único)."""
    from quem_e_este_leao.publish import get_publisher
    from quem_e_este_leao.quiz import generate_quiz

    settings = _settings(difficulty, reveal_in, dry_run)
    quiz = generate_quiz(
        settings,
        difficulty=Difficulty(difficulty),
        reveal_delay=RevealDelay(reveal_in),
        output_dir=settings.preview_dir if settings.dry_run else settings.output_dir,
    )
    remote = get_publisher(settings).publish_quiz(quiz.quiz_id)
    typer.echo(f"Quiz {quiz.quiz_id} publicado" + (f" → {remote}" if remote else ""))


@app.command("serve-scheduler")
def serve_scheduler_cmd() -> None:
    """Corre o APScheduler em primeiro plano (revelações a cada 5 min)."""
    from quem_e_este_leao.schedule import serve_scheduler

    settings = _settings()
    typer.echo("Agendador a correr (Ctrl+C para parar). Fuso: Europe/Lisbon.")
    serve_scheduler(settings)


@app.command("list-formats")
def list_formats_cmd() -> None:
    """Lista formatos de quiz (implementados e esqueletos)."""
    from quem_e_este_leao.formats.base import list_formats

    _settings()
    for fmt in list_formats():
        typer.echo(fmt.describe())


if __name__ == "__main__":
    app()
