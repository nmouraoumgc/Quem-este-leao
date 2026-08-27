"""Persistência SQLite: quizzes, respostas (tabela separada) e rotação."""

from __future__ import annotations

import random
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Sequence

from quem_e_este_leao.config import PROJECT_ROOT
from quem_e_este_leao.logging_setup import get_logger, log_answer
from quem_e_este_leao.players import Player

log = get_logger("db")

SCHEMA_PATH = PROJECT_ROOT / "schema.sql"

STATUS_DRAFT = "draft"
STATUS_PUBLISHED = "published"
STATUS_REVEALED = "revealed"


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection, schema_path: Path | None = None) -> None:
    path = schema_path or SCHEMA_PATH
    sql = path.read_text(encoding="utf-8")
    conn.executescript(sql)
    conn.commit()


@contextmanager
def session(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        init_db(conn)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def current_cycle(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT cycle_id FROM rotation_state WHERE id = 1").fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO rotation_state (id, cycle_id, updated_at) VALUES (1, 1, ?)",
            (_now(),),
        )
        return 1
    return int(row["cycle_id"])


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def used_player_ids(conn: sqlite3.Connection, cycle_id: int) -> set[str]:
    rows = conn.execute(
        "SELECT player_id FROM players_used WHERE cycle_id = ?", (cycle_id,)
    ).fetchall()
    return {r["player_id"] for r in rows}


def mark_used(conn: sqlite3.Connection, player_id: str, cycle_id: int) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO players_used (player_id, cycle_id, used_at) VALUES (?, ?, ?)",
        (player_id, cycle_id, _now()),
    )


def bump_cycle(conn: sqlite3.Connection) -> int:
    new_id = current_cycle(conn) + 1
    conn.execute(
        "UPDATE rotation_state SET cycle_id = ?, updated_at = ? WHERE id = 1",
        (new_id, _now()),
    )
    log.info("Novo ciclo de rotação: %s", new_id)
    return new_id


def select_player(
    conn: sqlite3.Connection,
    players: Sequence[Player],
    rng: random.Random | None = None,
    *,
    exclude: set[str] | None = None,
) -> Player:
    """Escolhe um jogador aleatório que ainda não saiu neste ciclo.

    Não se repete até o pool inteiro ter sido usado. `exclude` serve para
    saltar candidatos cuja fotografia falhou neste pedido (não os marca usados).
    """
    rng = rng or random.Random()
    exclude = exclude or set()
    if not players:
        raise RuntimeError("A base de jogadores está vazia.")

    cycle = current_cycle(conn)
    used = used_player_ids(conn, cycle)
    pool = [p for p in players if p.id not in used and p.id not in exclude]
    if not pool:
        # Se o único que resta está em exclude, não avançar ciclo ainda.
        remaining = [p for p in players if p.id not in used]
        if remaining and remaining and all(p.id in exclude for p in remaining):
            raise RuntimeError(
                "Não há candidatos utilizáveis neste ciclo (fotografias falharam)."
            )
        cycle = bump_cycle(conn)
        used = used_player_ids(conn, cycle)
        pool = [p for p in players if p.id not in used and p.id not in exclude]
        if not pool:
            pool = [p for p in players if p.id not in exclude]
    chosen = rng.choice(list(pool))
    mark_used(conn, chosen.id, cycle)
    log.info("Jogador seleccionado no ciclo %s (id interno omitido no INFO).", cycle)
    log_answer("Jogador seleccionado: %s (%s)", chosen.display_name, chosen.id)
    return chosen


def insert_quiz(
    conn: sqlite3.Connection,
    *,
    quiz_id: str,
    format_id: str,
    player: Player,
    original_image_path: str | None,
    processed_image_path: str,
    clue: str,
    caption: str,
    reveal_caption: str,
    reveal_dt: str | None,
    status: str,
    difficulty: str,
    image_attribution: str | None,
    interesting_fact: str | None,
) -> None:
    conn.execute(
        """
        INSERT INTO quizzes (
            id, format_id, player_id, original_image_path, processed_image_path,
            clue, caption, reveal_caption, publication_dt, reveal_dt, status,
            difficulty, image_attribution, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?)
        """,
        (
            quiz_id,
            format_id,
            player.id,
            original_image_path,
            processed_image_path,
            clue,
            caption,
            reveal_caption,
            reveal_dt,
            status,
            difficulty,
            image_attribution,
            _now(),
        ),
    )
    conn.execute(
        """
        INSERT INTO quiz_answers (quiz_id, correct_answer, interesting_fact)
        VALUES (?, ?, ?)
        """,
        (quiz_id, player.display_name, interesting_fact),
    )


def get_quiz(conn: sqlite3.Connection, quiz_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM quizzes WHERE id = ?", (quiz_id,)).fetchone()


def get_answer(conn: sqlite3.Connection, quiz_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM quiz_answers WHERE quiz_id = ?", (quiz_id,)
    ).fetchone()


def list_due_reveals(conn: sqlite3.Connection, now_iso: str) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT * FROM quizzes
            WHERE status = ? AND reveal_dt IS NOT NULL AND reveal_dt <= ?
            ORDER BY reveal_dt ASC
            """,
            (STATUS_PUBLISHED, now_iso),
        ).fetchall()
    )


def mark_published(
    conn: sqlite3.Connection,
    quiz_id: str,
    *,
    publication_dt: str,
    reveal_dt: str,
    channel: str,
    remote_id: str | None,
) -> None:
    conn.execute(
        """
        UPDATE quizzes
        SET status = ?, publication_dt = ?, reveal_dt = ?
        WHERE id = ?
        """,
        (STATUS_PUBLISHED, publication_dt, reveal_dt, quiz_id),
    )
    conn.execute(
        """
        INSERT INTO publications (quiz_id, channel, remote_id, kind, published_at)
        VALUES (?, ?, ?, 'quiz', ?)
        """,
        (quiz_id, channel, remote_id, publication_dt),
    )


def mark_revealed(
    conn: sqlite3.Connection,
    quiz_id: str,
    *,
    channel: str,
    remote_id: str | None,
) -> None:
    now = _now()
    conn.execute(
        "UPDATE quizzes SET status = ? WHERE id = ?",
        (STATUS_REVEALED, quiz_id),
    )
    conn.execute(
        """
        INSERT INTO publications (quiz_id, channel, remote_id, kind, published_at)
        VALUES (?, ?, ?, 'reveal', ?)
        """,
        (quiz_id, channel, remote_id, now),
    )


def latest_draft(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM quizzes WHERE status = ? ORDER BY created_at DESC LIMIT 1",
        (STATUS_DRAFT,),
    ).fetchone()


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {k: row[k] for k in row.keys()}
