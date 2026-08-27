"""CLI: generate, preview, publish, reveal, players, reset, status, scheduler."""

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


def _resolve_player(settings: Settings, slug: Optional[str]):
    if not slug:
        return None
    from quem_e_este_leao.players import get_player, load_players

    return get_player(load_players(settings.players_yaml), slug)


@app.command()
def generate(
    difficulty: str = typer.Option("medium", "--difficulty", "-d", help="easy | medium | hard"),
    reveal_in: str = typer.Option("1h", "--reveal-in", help="30min | 1h | 3h"),
    output_dir: Optional[Path] = typer.Option(None, "--output-dir", "-o"),
    player: Optional[str] = typer.Option(None, "--player", help="Slug interno (ex.: luis-figo)"),
    player_id: Optional[str] = typer.Option(None, "--player-id", hidden=True),
    dry_run: bool = typer.Option(True, "--dry-run/--no-dry-run"),
) -> None:
    """Gera um quiz (imagem + legenda) em rascunho. Não revela o nome."""
    from quem_e_este_leao.quiz import generate_quiz

    settings = _settings(difficulty, reveal_in, dry_run)
    out = output_dir or (settings.preview_dir if settings.dry_run else settings.output_dir)
    slug = player or player_id
    chosen = _resolve_player(settings, slug)
    quiz = generate_quiz(
        settings,
        difficulty=Difficulty(difficulty),
        reveal_delay=RevealDelay(reveal_in),
        output_dir=out,
        player=chosen,
        allow_synthetic=settings.allow_synthetic,
    )
    typer.echo(f"Quiz gerado: {quiz.quiz_id}")
    typer.echo(f"Imagem: {quiz.processed_image}")
    typer.echo("Legenda:")
    typer.echo(quiz.caption)


@app.command()
def preview(
    difficulty: str = typer.Option("medium", "--difficulty", "-d", help="easy | medium | hard"),
    reveal_in: str = typer.Option("1h", "--reveal-in", help="30min | 1h | 3h"),
    output_dir: Optional[Path] = typer.Option(None, "--output-dir", "-o"),
    player: Optional[str] = typer.Option(None, "--player", help="Slug interno (ex.: luis-figo)"),
) -> None:
    """Alias de `generate --dry-run` — só pré-visualização local."""
    generate(
        difficulty=difficulty,
        reveal_in=reveal_in,
        output_dir=output_dir,
        player=player,
        player_id=None,
        dry_run=True,
    )


@app.command()
def publish(
    quiz_id_arg: Optional[str] = typer.Argument(None, help="ID do quiz"),
    quiz_id: Optional[str] = typer.Option(None, "--quiz-id"),
    dry_run: bool = typer.Option(True, "--dry-run/--no-dry-run"),
) -> None:
    """Publica um rascunho (local por omissão; X se houver credenciais)."""
    from quem_e_este_leao import db
    from quem_e_este_leao.publish import get_publisher

    settings = _settings(dry_run=dry_run)
    qid = quiz_id_arg or quiz_id
    with db.session(settings.database_path) as conn:
        row = db.get_quiz(conn, qid) if qid else db.latest_draft(conn)
        if row is None:
            raise typer.BadParameter("Não há rascunho para publicar.")
        qid = row["id"]
    remote = get_publisher(settings).publish_quiz(qid)
    typer.echo(f"Publicado {qid}" + (f" → {remote}" if remote else ""))


@app.command()
def reveal(
    quiz_id_arg: Optional[str] = typer.Argument(None, help="ID do quiz"),
    quiz_id: Optional[str] = typer.Option(None, "--quiz-id"),
    dry_run: bool = typer.Option(True, "--dry-run/--no-dry-run"),
) -> None:
    """Publica a revelação de um quiz."""
    from quem_e_este_leao.publish import get_publisher

    settings = _settings(dry_run=dry_run)
    qid = quiz_id_arg or quiz_id
    if not qid:
        raise typer.BadParameter("Indica o QUIZ_ID.")
    remote = get_publisher(settings).publish_reveal(qid)
    typer.echo(f"Revelado {qid}" + (f" → {remote}" if remote else ""))


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
        allow_synthetic=settings.allow_synthetic,
    )
    remote = get_publisher(settings).publish_quiz(quiz.quiz_id)
    typer.echo(f"Quiz {quiz.quiz_id} publicado" + (f" → {remote}" if remote else ""))


@app.command("serve-scheduler")
def serve_scheduler_cmd() -> None:
    """Corre o APScheduler em primeiro plano (post diário + revelações)."""
    from quem_e_este_leao.schedule import serve_scheduler

    settings = _settings()
    typer.echo(
        f"Agendador a correr (Ctrl+C para parar). Fuso: {settings.timezone}. "
        f"Post diário: {settings.post_at}."
    )
    serve_scheduler(settings)


@app.command()
def players() -> None:
    """Lista os jogadores da base (YAML)."""
    from quem_e_este_leao.players import load_players

    settings = _settings()
    for p in load_players(settings.players_yaml):
        typer.echo(f"{p.id:28} {p.display_name:28} {p.position:18} {p.years_at_sporting}")


@app.command()
def reset(
    yes: bool = typer.Option(False, "--yes", "-y", help="Confirma o reset da rotação"),
) -> None:
    """Reinicia o ciclo de rotação (não apaga quizzes)."""
    from quem_e_este_leao import db

    if not yes:
        raise typer.BadParameter("Passa --yes para confirmar o reset da rotação.")
    settings = _settings()
    with db.session(settings.database_path) as conn:
        db.reset_rotation(conn)
    typer.echo("Rotação reiniciada.")


@app.command()
def status() -> None:
    """Mostra ciclo de rotação, quizzes e próxima revelação."""
    from quem_e_este_leao import db
    from quem_e_este_leao.players import load_players

    settings = _settings()
    players_list = load_players(settings.players_yaml)
    with db.session(settings.database_path) as conn:
        snap = db.status_snapshot(conn, len(players_list))
        due = db.list_due_reveals(conn, "9999-12-31T23:59:59")
        next_reveal = due[0]["id"] if due else None
        next_at = (due[0]["reveal_at"] or due[0]["reveal_dt"]) if due else None
    typer.echo(f"Ciclo de rotação: {snap['cycle_id']}")
    typer.echo(
        f"Jogadores no pool: {snap['players_in_pool']} "
        f"(usados neste ciclo: {snap['used_this_cycle']}, "
        f"restantes: {snap['remaining_this_cycle']})"
    )
    typer.echo(
        f"Quizzes: {snap['total_quizzes']} "
        f"(rascunho {snap['drafts']}, publicados {snap['published']}, "
        f"revelados {snap['revealed']})"
    )
    typer.echo(f"Último post diário: {snap['last_daily_post_date'] or '—'}")
    typer.echo(f"Próxima revelação: {next_reveal or '—'} {next_at or ''}".rstrip())
    typer.echo(f"Dry-run: {settings.dry_run}  |  Sintético: {settings.allow_synthetic}")
    typer.echo(f"Post diário (QEEL_POST_AT): {settings.post_at} {settings.timezone}")


@app.command("list-formats")
def list_formats_cmd() -> None:
    """Lista formatos de quiz (implementados e esqueletos)."""
    from quem_e_este_leao.formats.base import list_formats

    _settings()
    for fmt in list_formats():
        typer.echo(fmt.describe())


if __name__ == "__main__":
    app()
