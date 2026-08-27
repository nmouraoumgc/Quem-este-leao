"""Persistência SQLite: quizzes, respostas (tabela separada) e rotação."""

from __future__ import annotations

import random
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Sequence
from zoneinfo import ZoneInfo

from quem_e_este_leao.config import PROJECT_ROOT, ImageKind
from quem_e_este_leao.logging_setup import get_logger, log_answer
from quem_e_este_leao.players import Player

log = get_logger("db")

SCHEMA_PATH = PROJECT_ROOT / "schema.sql"
TZ = ZoneInfo("Europe/Lisbon")

STATUS_DRAFT = "draft"
STATUS_PUBLISHED = "published"
STATUS_REVEALED = "revealed"

_QUIZ_NEW_COLUMNS: tuple[tuple[str, str], ...] = (
    ("image_source", "TEXT"),
    ("image_kind", "TEXT NOT NULL DEFAULT 'REAL'"),
    ("published_at", "TEXT"),
    ("reveal_at", "TEXT"),
    ("revealed_at", "TEXT"),
    ("x_quiz_post_id", "TEXT"),
    ("x_reveal_post_id", "TEXT"),
)

_ANSWER_NEW_COLUMNS: tuple[tuple[str, str], ...] = (
    ("player_name", "TEXT"),
)


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {r[1] for r in rows}


def _add_missing_columns(
    conn: sqlite3.Connection, table: str, columns: Sequence[tuple[str, str]]
) -> None:
    existing = _table_columns(conn, table)
    if not existing:
        return
    for name, typedef in columns:
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {typedef}")
            log.info("Migração: coluna %s.%s adicionada.", table, name)


def migrate(conn: sqlite3.Connection) -> None:
    """Extensões compatíveis com bases já existentes (não parte linhas antigas)."""
    _add_missing_columns(conn, "quizzes", _QUIZ_NEW_COLUMNS)
    _add_missing_columns(conn, "quiz_answers", _ANSWER_NEW_COLUMNS)
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_publications_quiz_kind
        ON publications (quiz_id, kind)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS scheduler_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            last_daily_post_date TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO scheduler_state (id, last_daily_post_date, updated_at)
        VALUES (1, NULL, ?)
        """,
        (_now(),),
    )
    # Espelhar colunas novas a partir das antigas, sem tocar em valores já preenchidos.
    if "reveal_at" in _table_columns(conn, "quizzes"):
        conn.execute(
            "UPDATE quizzes SET reveal_at = reveal_dt WHERE reveal_at IS NULL AND reveal_dt IS NOT NULL"
        )
        conn.execute(
            "UPDATE quizzes SET published_at = publication_dt "
            "WHERE published_at IS NULL AND publication_dt IS NOT NULL"
        )
    if "player_name" in _table_columns(conn, "quiz_answers"):
        conn.execute(
            "UPDATE quiz_answers SET player_name = correct_answer "
            "WHERE player_name IS NULL AND correct_answer IS NOT NULL"
        )


def init_db(conn: sqlite3.Connection, schema_path: Path | None = None) -> None:
    path = schema_path or SCHEMA_PATH
    sql = path.read_text(encoding="utf-8")
    conn.executescript(sql)
    migrate(conn)
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
    return datetime.now(TZ).isoformat(timespec="seconds")


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


def reset_rotation(conn: sqlite3.Connection) -> int:
    """Reinicia o ciclo (não apaga quizzes)."""
    conn.execute(
        "UPDATE rotation_state SET cycle_id = 1, updated_at = ? WHERE id = 1",
        (_now(),),
    )
    conn.execute("DELETE FROM players_used")
    log.info("Rotação reiniciada.")
    return 1


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
        remaining = [p for p in players if p.id not in used]
        if remaining and all(p.id in exclude for p in remaining):
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


def _has_col(conn: sqlite3.Connection, table: str, col: str) -> bool:
    return col in _table_columns(conn, table)


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
    image_source: str | None = None,
    image_kind: str | None = None,
) -> None:
    kind = image_kind or ImageKind.REAL.value
    cols = _table_columns(conn, "quizzes")
    fields = [
        "id",
        "format_id",
        "player_id",
        "original_image_path",
        "processed_image_path",
        "clue",
        "caption",
        "reveal_caption",
        "publication_dt",
        "reveal_dt",
        "status",
        "difficulty",
        "image_attribution",
        "created_at",
    ]
    values: list[Any] = [
        quiz_id,
        format_id,
        player.id,
        original_image_path,
        processed_image_path,
        clue,
        caption,
        reveal_caption,
        None,
        reveal_dt,
        status,
        difficulty,
        image_attribution,
        _now(),
    ]
    extra = {
        "image_source": image_source,
        "image_kind": kind,
        "published_at": None,
        "reveal_at": reveal_dt,
        "revealed_at": None,
        "x_quiz_post_id": None,
        "x_reveal_post_id": None,
    }
    for name, val in extra.items():
        if name in cols:
            fields.append(name)
            values.append(val)
    placeholders = ", ".join("?" * len(fields))
    conn.execute(
        f"INSERT INTO quizzes ({', '.join(fields)}) VALUES ({placeholders})",
        values,
    )
    ans_cols = _table_columns(conn, "quiz_answers")
    if "player_name" in ans_cols:
        conn.execute(
            """
            INSERT INTO quiz_answers (quiz_id, correct_answer, interesting_fact, player_name)
            VALUES (?, ?, ?, ?)
            """,
            (quiz_id, player.display_name, interesting_fact, player.display_name),
        )
    else:
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
    # reveal_at (novo) OU reveal_dt (legado)
    return list(
        conn.execute(
            """
            SELECT * FROM quizzes
            WHERE status = ?
              AND (
                    (reveal_at IS NOT NULL AND reveal_at <= ?)
                 OR (reveal_at IS NULL AND reveal_dt IS NOT NULL AND reveal_dt <= ?)
              )
            ORDER BY COALESCE(reveal_at, reveal_dt) ASC
            """,
            (STATUS_PUBLISHED, now_iso, now_iso),
        ).fetchall()
    )


def get_publication(
    conn: sqlite3.Connection, quiz_id: str, kind: str
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM publications WHERE quiz_id = ? AND kind = ?",
        (quiz_id, kind),
    ).fetchone()


def mark_published(
    conn: sqlite3.Connection,
    quiz_id: str,
    *,
    publication_dt: str,
    reveal_dt: str,
    channel: str,
    remote_id: str | None,
) -> bool:
    """Marca publicado de forma idempotente. Devolve False se já estava publicado."""
    row = get_quiz(conn, quiz_id)
    if row is None:
        raise KeyError(f"Quiz inexistente: {quiz_id}")
    existing = get_publication(conn, quiz_id, "quiz")
    if row["status"] in (STATUS_PUBLISHED, STATUS_REVEALED) or existing is not None:
        log.info("Publicação do quiz %s já existia — retry ignorado.", quiz_id)
        return False
    cols = _table_columns(conn, "quizzes")
    sets = ["status = ?", "publication_dt = ?", "reveal_dt = ?"]
    args: list[Any] = [STATUS_PUBLISHED, publication_dt, reveal_dt]
    if "published_at" in cols:
        sets.append("published_at = ?")
        args.append(publication_dt)
    if "reveal_at" in cols:
        sets.append("reveal_at = ?")
        args.append(reveal_dt)
    if "x_quiz_post_id" in cols and channel == "x" and remote_id:
        sets.append("x_quiz_post_id = ?")
        args.append(remote_id)
    args.append(quiz_id)
    conn.execute(f"UPDATE quizzes SET {', '.join(sets)} WHERE id = ?", args)
    try:
        conn.execute(
            """
            INSERT INTO publications (quiz_id, channel, remote_id, kind, published_at)
            VALUES (?, ?, ?, 'quiz', ?)
            """,
            (quiz_id, channel, remote_id, publication_dt),
        )
    except sqlite3.IntegrityError:
        log.info("Constraint única: publicação quiz %s já registada.", quiz_id)
        return False
    return True


def mark_revealed(
    conn: sqlite3.Connection,
    quiz_id: str,
    *,
    channel: str,
    remote_id: str | None,
) -> bool:
    row = get_quiz(conn, quiz_id)
    if row is None:
        raise KeyError(f"Quiz inexistente: {quiz_id}")
    existing = get_publication(conn, quiz_id, "reveal")
    if row["status"] == STATUS_REVEALED or existing is not None:
        log.info("Revelação do quiz %s já existia — retry ignorado.", quiz_id)
        return False
    now = _now()
    cols = _table_columns(conn, "quizzes")
    sets = ["status = ?"]
    args: list[Any] = [STATUS_REVEALED]
    if "revealed_at" in cols:
        sets.append("revealed_at = ?")
        args.append(now)
    if "x_reveal_post_id" in cols and channel == "x" and remote_id:
        sets.append("x_reveal_post_id = ?")
        args.append(remote_id)
    args.append(quiz_id)
    conn.execute(f"UPDATE quizzes SET {', '.join(sets)} WHERE id = ?", args)
    try:
        conn.execute(
            """
            INSERT INTO publications (quiz_id, channel, remote_id, kind, published_at)
            VALUES (?, ?, ?, 'reveal', ?)
            """,
            (quiz_id, channel, remote_id, now),
        )
    except sqlite3.IntegrityError:
        log.info("Constraint única: revelação quiz %s já registada.", quiz_id)
        return False
    return True


def latest_draft(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM quizzes WHERE status = ? ORDER BY created_at DESC LIMIT 1",
        (STATUS_DRAFT,),
    ).fetchone()


def count_quizzes(conn: sqlite3.Connection, status: str | None = None) -> int:
    if status:
        row = conn.execute("SELECT COUNT(*) AS n FROM quizzes WHERE status = ?", (status,)).fetchone()
    else:
        row = conn.execute("SELECT COUNT(*) AS n FROM quizzes").fetchone()
    return int(row["n"] if row else 0)


def published_on_date(conn: sqlite3.Connection, date_iso: str) -> bool:
    """Há alguma publicação de quiz neste dia civil (YYYY-MM-DD)?"""
    row = conn.execute(
        """
        SELECT 1 FROM quizzes
        WHERE status IN (?, ?)
          AND (
                (published_at IS NOT NULL AND substr(published_at, 1, 10) = ?)
             OR (published_at IS NULL AND publication_dt IS NOT NULL
                 AND substr(publication_dt, 1, 10) = ?)
          )
        LIMIT 1
        """,
        (STATUS_PUBLISHED, STATUS_REVEALED, date_iso, date_iso),
    ).fetchone()
    if row:
        return True
    row = conn.execute(
        """
        SELECT 1 FROM publications
        WHERE kind = 'quiz' AND substr(published_at, 1, 10) = ?
        LIMIT 1
        """,
        (date_iso,),
    ).fetchone()
    return row is not None


def get_last_daily_post_date(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT last_daily_post_date FROM scheduler_state WHERE id = 1"
    ).fetchone()
    if row is None:
        return None
    return row["last_daily_post_date"]


def set_last_daily_post_date(conn: sqlite3.Connection, date_iso: str) -> None:
    conn.execute(
        """
        INSERT INTO scheduler_state (id, last_daily_post_date, updated_at)
        VALUES (1, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            last_daily_post_date = excluded.last_daily_post_date,
            updated_at = excluded.updated_at
        """,
        (date_iso, _now()),
    )


def status_snapshot(conn: sqlite3.Connection, n_players: int) -> dict[str, Any]:
    cycle = current_cycle(conn)
    used = used_player_ids(conn, cycle)
    return {
        "cycle_id": cycle,
        "players_in_pool": n_players,
        "used_this_cycle": len(used),
        "remaining_this_cycle": max(0, n_players - len(used)),
        "drafts": count_quizzes(conn, STATUS_DRAFT),
        "published": count_quizzes(conn, STATUS_PUBLISHED),
        "revealed": count_quizzes(conn, STATUS_REVEALED),
        "total_quizzes": count_quizzes(conn),
        "last_daily_post_date": get_last_daily_post_date(conn),
    }


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {k: row[k] for k in row.keys()}
