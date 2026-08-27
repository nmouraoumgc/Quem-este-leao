from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from quem_e_este_leao import db
from quem_e_este_leao.config import Difficulty, Settings
from quem_e_este_leao.images import generate_synthetic_kit_photo
from quem_e_este_leao.processing import Box, opaque_filename, process_to_post
from quem_e_este_leao.publish import LocalPreviewPublisher, XPublisher, get_publisher
from quem_e_este_leao.quiz import new_quiz_id
from quem_e_este_leao.players import load_players


def _seed_draft(settings: Settings, tmp_path) -> str:
    players = load_players(settings.players_yaml)
    player = next(p for p in players if p.local_image)
    quiz_id = new_quiz_id()
    src = generate_synthetic_kit_photo(tmp_path / "s.jpg").path
    dest = tmp_path / opaque_filename(quiz_id)
    process_to_post(
        src,
        dest,
        Difficulty.EASY,
        abort_if_recognizable=False,
        forced_faces=[Box(380, 210, 140, 190)],
        second_pass=False,
    )
    with db.session(settings.database_path) as conn:
        db.insert_quiz(
            conn,
            quiz_id=quiz_id,
            format_id="quem_e_este_leao",
            player=player,
            original_image_path=str(src),
            processed_image_path=str(dest),
            clue="É português.",
            caption="pista pública",
            reveal_caption="Era o X",
            reveal_dt=(datetime.now(ZoneInfo("Europe/Lisbon")) + timedelta(hours=1)).isoformat(),
            status=db.STATUS_DRAFT,
            difficulty="medium",
            image_attribution=None,
            interesting_fact=None,
            image_source="synthetic",
            image_kind="SYNTHETIC_TEST",
        )
    return quiz_id


def test_local_publish_is_idempotent(tmp_settings, tmp_path) -> None:
    qid = _seed_draft(tmp_settings, tmp_path)
    pub = LocalPreviewPublisher(tmp_settings)
    a = pub.publish_quiz(qid)
    b = pub.publish_quiz(qid)
    assert a == b
    with db.session(tmp_settings.database_path) as conn:
        rows = conn.execute(
            "SELECT COUNT(*) AS n FROM publications WHERE quiz_id = ? AND kind = 'quiz'",
            (qid,),
        ).fetchone()
        assert int(rows["n"]) == 1
        assert db.get_quiz(conn, qid)["status"] == db.STATUS_PUBLISHED


def test_get_publisher_dry_run_is_local(tmp_settings) -> None:
    assert isinstance(get_publisher(tmp_settings), LocalPreviewPublisher)


class _FakeMedia:
    media_id = 99


class _FakeTweet:
    data = {"id": "777"}


class _FakeAPI:
    def __init__(self) -> None:
        self.uploads = 0

    def media_upload(self, path):
        self.uploads += 1
        return _FakeMedia()


class _FakeClient:
    def __init__(self) -> None:
        self.tweets = 0

    def create_tweet(self, text, media_ids=None):
        self.tweets += 1
        return _FakeTweet()


def test_x_publish_idempotent_with_mock(tmp_settings, tmp_path) -> None:
    qid = _seed_draft(tmp_settings, tmp_path)
    api = _FakeAPI()
    client = _FakeClient()
    creds = tmp_settings.model_copy(
        update={
            "x_api_key": "k",
            "x_api_secret": "s",
            "x_access_token": "t",
            "x_access_token_secret": "ts",
            "dry_run": False,
        }
    )
    pub = XPublisher(creds, client=client, api_v1=api)
    a = pub.publish_quiz(qid)
    b = pub.publish_quiz(qid)
    assert a == "777"
    assert b == "777"
    assert client.tweets == 1
    assert api.uploads == 1
    with db.session(tmp_settings.database_path) as conn:
        row = db.get_quiz(conn, qid)
        assert row["x_quiz_post_id"] == "777"
        assert row["status"] == db.STATUS_PUBLISHED
