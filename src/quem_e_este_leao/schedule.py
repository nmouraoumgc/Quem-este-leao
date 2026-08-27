"""Agendamento: APScheduler em processo e comando cron `reveal-due`."""

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


def build_scheduler(settings: Settings):  # type: ignore[no-untyped-def]
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.interval import IntervalTrigger

    scheduler = BlockingScheduler(timezone=settings.timezone)

    def _job() -> None:
        reveal_due(settings)

    scheduler.add_job(
        _job,
        IntervalTrigger(minutes=5, timezone=settings.timezone),
        id="reveal-due",
        replace_existing=True,
    )
    log.info("Agendador activo (Europe/Lisbon, a cada 5 min).")
    return scheduler


def serve_scheduler(settings: Settings) -> None:
    scheduler = build_scheduler(settings)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Agendador interrompido.")
