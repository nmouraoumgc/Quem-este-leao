from __future__ import annotations

import re

from quem_e_este_leao.clues import contains_identity
from quem_e_este_leao.config import Difficulty
from quem_e_este_leao.images import generate_synthetic_kit_photo
from quem_e_este_leao.players import load_players
from quem_e_este_leao.processing import Box, opaque_filename, process_to_post
from quem_e_este_leao.quiz import generate_quiz, new_quiz_id


def test_opaque_filename_pattern() -> None:
    name = opaque_filename("deadbeefcafebabe")
    assert name == "quiz_deadbeefcafebabe.jpg"
    assert re.fullmatch(r"quiz_[0-9a-f]+\.jpg", name)


def test_generated_filename_never_contains_player_name(tmp_settings, tmp_path) -> None:
    players = load_players(tmp_settings.players_yaml)
    # jogador com foto local para ser determinístico e offline
    local = [p for p in players if p.local_image]
    player = local[0] if local else players[0]
    quiz = generate_quiz(
        tmp_settings,
        difficulty=Difficulty.MEDIUM,
        player=player,
        allow_synthetic=True,
        output_dir=tmp_path,
    )
    assert quiz.processed_image.name.startswith("quiz_")
    assert quiz.processed_image.suffix == ".jpg"
    assert not contains_identity(quiz.processed_image.name, player)
    assert not contains_identity(quiz.caption, player)
    for token in player.identity_tokens:
        if len(token) >= 4:
            assert token.casefold() not in quiz.processed_image.name.casefold()


def test_process_output_name_is_opaque(tmp_path) -> None:
    src = generate_synthetic_kit_photo(tmp_path / "src.jpg").path
    dest = tmp_path / opaque_filename(new_quiz_id())
    process_to_post(
        src,
        dest,
        Difficulty.MEDIUM,
        abort_if_recognizable=False,
        forced_faces=[Box(380, 210, 140, 190)],
    )
    assert re.fullmatch(r"quiz_[0-9a-f]+\.jpg", dest.name)
    assert "figo" not in dest.name.lower()
    assert "gyokeres" not in dest.name.lower()
