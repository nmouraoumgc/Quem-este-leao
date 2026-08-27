from __future__ import annotations

from PIL import Image

from quem_e_este_leao.clues import contains_identity
from quem_e_este_leao.config import Difficulty
from quem_e_este_leao.players import get_player, load_players
from quem_e_este_leao.quiz import generate_quiz


def test_e2e_dry_run_known_player_real_photo(tmp_settings, tmp_path) -> None:
    players = load_players(tmp_settings.players_yaml)
    player = get_player(players, "nuno-santos")
    assert player.local_image
    quiz = generate_quiz(
        tmp_settings,
        difficulty=Difficulty.MEDIUM,
        player=player,
        allow_synthetic=False,
        output_dir=tmp_path,
    )
    assert quiz.image_kind == "REAL"
    assert quiz.image_source == "local"
    assert quiz.processed_image.exists()
    img = Image.open(quiz.processed_image)
    assert img.size == (1080, 1080)
    assert quiz.processed_image.name.startswith("quiz_")
    assert not contains_identity(quiz.caption, player)
    assert not contains_identity(quiz.processed_image.name, player)
    assert "QUEM É ESTE LEÃO" in quiz.caption
