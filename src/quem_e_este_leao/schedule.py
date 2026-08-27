"""Agendamento: APScheduler em processo e comando cron `reveal-due`.

Os trabalhos devidos (revelações) vivem no SQLite (`reveal_at`/`reveal_dt` +
`status`), não só em memória — um restart não perde o que já está publicado.
O post diário (`QEEL_POST_AT`) também consulta a BD (já houve post hoje?).
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from quem_e_este_leao import db
from quem_e_este_leao.config import Settings
from quem_e_este_leao.logging_setup import get_logger
from quem_e_este_leao.publish import Publisher, get_publisher

log = get_logger("schedule")


def due_iso(settings: Settings, now: datetime | None = None) -> str:
    tz = ZoneInfo(settings.timezone)
    current = now or datetime.now(tz)
    if current.tzinfo is None:
        current = current.replace(tzinfo=tz)
    return current.isoformat()


def reveal_due(
    settings: Settings,
    publisher: Publisher | None = None,
    now: datetime | None = None,
) -> list[str]:
    """Revela todos os quizzes publicados cuja hora de revelação já passou."""
    publisher = publisher or get_publisher(settings)
    revealed: list[str] = []
    with db.session(settings.database_path) as conn:
        rows = db.list_due_reveals(conn, due_iso(settings, now))
        ids = [r["id"] for r in rows]
    for quiz_id in ids:
        log.info("A revelar quiz devido %s.", quiz_id)
        publisher.publish_reveal(quiz_id)
        revealed.append(quiz_id)
    if not revealed:
        log.info("Nenhuma revelação em atraso.")
    return revealed


def should_run_daily_post(settings: Settings, now: datetime | None = None) -> bool:
    """True se já passou QEEL_POST_AT hoje e ainda não houve publicação."""
    tz = ZoneInfo(settings.timezone)
    current = now or datetime.now(tz)
    if current.tzinfo is None:
        current = current.replace(tzinfo=tz)
    hour, minute = settings.post_at_hour_minute
    today_slot = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if current < today_slot:
        return False
    date_iso = current.date().isoformat()
    with db.session(settings.database_path) as conn:
        if db.published_on_date(conn, date_iso):
            return False
        last = db.get_last_daily_post_date(conn)
        if last == date_iso:
            return False
    return True


def run_daily_post(settings: Settings, now: datetime | None = None) -> str | None:
    """Gera e publica o quiz do dia, se devido. Idempotente via SQLite."""
    if not should_run_daily_post(settings, now):
        log.info("Post diário não devido.")
        return None
    from quem_e_este_leao.quiz import generate_quiz

    tz = ZoneInfo(settings.timezone)
    current = now or datetime.now(tz)
    date_iso = current.date().isoformat()
    quiz = generate_quiz(
        settings,
        difficulty=settings.difficulty,
        reveal_delay=settings.reveal_delay,
        output_dir=settings.preview_dir if settings.dry_run else settings.output_dir,
        allow_synthetic=settings.allow_synthetic,
    )
    remote = get_publisher(settings).publish_quiz(quiz.quiz_id)
    with db.session(settings.database_path) as conn:
        db.set_last_daily_post_date(conn, date_iso)
    log.info("Post diário gerado (%s).", quiz.quiz_id)
    return quiz.quiz_id if remote or quiz.quiz_id else None


def build_scheduler(settings: Settings):  # type: ignore[no-untyped-def]
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger

    scheduler = BlockingScheduler(timezone=settings.timezone)

    def _reveal_job() -> None:
        reveal_due(settings)

    def _daily_job() -> None:
        try:
            run_daily_post(settings)
        except Exception as exc:  # noqa: BLE001
            log.error("Post diário falhou: %s", type(exc).__name__)

    scheduler.add_job(
        _reveal_job,
        IntervalTrigger(minutes=5, timezone=settings.timezone),
        id="reveal-due",
        replace_existing=True,
    )
    hour, minute = settings.post_at_hour_minute
    scheduler.add_job(
        _daily_job,
        CronTrigger(hour=hour, minute=minute, timezone=settings.timezone),
        id="daily-post",
        replace_existing=True,
    )
    log.info(
        "Agendador activo (%s, revelações a cada 5 min, post às %s).",
        settings.timezone,
        settings.post_at,
    )
    return scheduler


def serve_scheduler(settings: Settings) -> None:
    # Catch-up após restart: jobs devidos estão na BD.
    try:
        reveal_due(settings)
    except Exception as exc:  # noqa: BLE001
        log.warning("Catch-up de revelações falhou: %s", type(exc).__name__)
    try:
        run_daily_post(settings)
    except Exception as exc:  # noqa: BLE001
        log.warning("Catch-up do post diário falhou: %s", type(exc).__name__)
    scheduler = build_scheduler(settings)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Agendador interrompido.")
