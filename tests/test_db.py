from __future__ import annotations

from quem_e_este_leao import db
from quem_e_este_leao.config import Difficulty
from quem_e_este_leao.images import generate_synthetic_kit_photo
from quem_e_este_leao.players import load_players
from quem_e_este_leao.processing import Box, opaque_filename, process_to_post
from quem_e_este_leao.quiz import new_quiz_id


def test_new_columns_and_status_transitions(tmp_settings, tmp_path) -> None:
    players = load_players(tmp_settings.players_yaml)
    player = players[0]
    quiz_id = new_quiz_id()
    src = generate_synthetic_kit_photo(tmp_path / "s.jpg").path
    dest = tmp_path / opaque_filename(quiz_id)
    process_to_post(
        src, dest, Difficulty.EASY, abort_if_recognizable=False,
        forced_faces=[Box(380, 210, 140, 190)], second_pass=False,
    )
    with db.session(tmp_settings.database_path) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(quizzes)")}
        for needed in (
            "image_source", "image_kind", "published_at", "reveal_at",
            "revealed_at", "x_quiz_post_id", "x_reveal_post_id",
        ):
            assert needed in cols
        db.insert_quiz(
            conn,
            quiz_id=quiz_id,
            format_id="quem_e_este_leao",
            player=player,
            original_image_path=str(src),
            processed_image_path=str(dest),
            clue="É médio.",
            caption="cap",
            reveal_caption="rev",
            reveal_dt="2026-08-27T18:00:00+01:00",
            status=db.STATUS_DRAFT,
            difficulty="medium",
            image_attribution=None,
            interesting_fact=None,
            image_source="local",
            image_kind="REAL",
        )
        row = db.get_quiz(conn, quiz_id)
        assert row["status"] == db.STATUS_DRAFT
        assert row["image_kind"] == "REAL"
        assert row["image_source"] == "local"
        ans = db.get_answer(conn, quiz_id)
        assert ans["player_name"] == player.display_name
        db.mark_published(
            conn, quiz_id,
            publication_dt="2026-08-27T12:00:00+01:00",
            reveal_dt="2026-08-27T13:00:00+01:00",
            channel="local",
            remote_id="/tmp/x.jpg",
        )
        assert db.get_quiz(conn, quiz_id)["status"] == db.STATUS_PUBLISHED
        # idempotent
        again = db.mark_published(
            conn, quiz_id,
            publication_dt="2026-08-27T12:01:00+01:00",
            reveal_dt="2026-08-27T13:00:00+01:00",
            channel="local",
            remote_id="/tmp/y.jpg",
        )
        assert again is False
        db.mark_revealed(conn, quiz_id, channel="local", remote_id="/tmp/r.txt")
        assert db.get_quiz(conn, quiz_id)["status"] == db.STATUS_REVEALED
        assert db.mark_revealed(conn, quiz_id, channel="local", remote_id="/tmp/r2.txt") is False


def test_reset_rotation(tmp_settings) -> None:
    from tests.helpers import make_player
    import random

    players = [make_player(id="a"), make_player(id="b")]
    with db.session(tmp_settings.database_path) as conn:
        db.select_player(conn, players, random.Random(0))
        assert db.current_cycle(conn) == 1
        assert db.used_player_ids(conn, 1)
        db.reset_rotation(conn)
        assert db.current_cycle(conn) == 1
        assert not db.used_player_ids(conn, 1)
