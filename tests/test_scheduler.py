from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from quem_e_este_leao import db
from quem_e_este_leao.config import Difficulty
from quem_e_este_leao.images import generate_synthetic_kit_photo
from quem_e_este_leao.players import load_players
from quem_e_este_leao.processing import Box, opaque_filename, process_to_post
from quem_e_este_leao.publish import LocalPreviewPublisher
from quem_e_este_leao.quiz import new_quiz_id
from quem_e_este_leao.schedule import reveal_due


def test_reveal_due_picks_published_past_deadline(tmp_settings, tmp_path) -> None:
    tz = ZoneInfo("Europe/Lisbon")
    now = datetime.now(tz)
    players = load_players(tmp_settings.players_yaml)
    player = next(p for p in players if p.local_image) if any(p.local_image for p in players) else players[0]
    quiz_id = new_quiz_id()
    src = generate_synthetic_kit_photo(tmp_path / "s.jpg").path
    dest = tmp_path / opaque_filename(quiz_id)
    process_to_post(
        src,
        dest,
        Difficulty.EASY,
        abort_if_recognizable=False,
        forced_faces=[Box(380, 210, 140, 190)],
    )
    with db.session(tmp_settings.database_path) as conn:
        db.insert_quiz(
            conn,
            quiz_id=quiz_id,
            format_id="quem_e_este_leao",
            player=player,
            original_image_path=str(src),
            processed_image_path=str(dest),
            clue="É português.",
            caption="pista",
            reveal_caption="Era o X",
            reveal_dt=(now - timedelta(minutes=5)).isoformat(),
            status=db.STATUS_PUBLISHED,
            difficulty="medium",
            image_attribution=None,
            interesting_fact=None,
        )
        future_id = new_quiz_id()
        db.insert_quiz(
            conn,
            quiz_id=future_id,
            format_id="quem_e_este_leao",
            player=player,
            original_image_path=str(src),
            processed_image_path=str(dest),
            clue="É avançado.",
            caption="pista2",
            reveal_caption="Era o Y",
            reveal_dt=(now + timedelta(hours=3)).isoformat(),
            status=db.STATUS_PUBLISHED,
            difficulty="medium",
            image_attribution=None,
            interesting_fact=None,
        )

    publisher = LocalPreviewPublisher(tmp_settings)
    revealed = reveal_due(tmp_settings, publisher=publisher, now=now)
    assert quiz_id in revealed
    assert future_id not in revealed
    with db.session(tmp_settings.database_path) as conn:
        assert db.get_quiz(conn, quiz_id)["status"] == db.STATUS_REVEALED
        assert db.get_quiz(conn, future_id)["status"] == db.STATUS_PUBLISHED

def test_daily_post_due_uses_sqlite(tmp_settings) -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from quem_e_este_leao.schedule import should_run_daily_post

    tz = ZoneInfo("Europe/Lisbon")
    before = datetime(2026, 8, 27, 11, 0, tzinfo=tz)
    after = datetime(2026, 8, 27, 12, 5, tzinfo=tz)
    assert should_run_daily_post(tmp_settings, before) is False
    assert should_run_daily_post(tmp_settings, after) is True
    with db.session(tmp_settings.database_path) as conn:
        db.set_last_daily_post_date(conn, "2026-08-27")
    assert should_run_daily_post(tmp_settings, after) is False

