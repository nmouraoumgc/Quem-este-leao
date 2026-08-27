from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image

from quem_e_este_leao.clues import contains_identity
from quem_e_este_leao.config import Difficulty
from quem_e_este_leao.players import load_players
from quem_e_este_leao.quiz import generate_quiz


def test_caption_filename_exif_logs_have_no_identity(tmp_settings, tmp_path, caplog) -> None:
    players = load_players(tmp_settings.players_yaml)
    player = next(p for p in players if p.local_image)
    caplog.set_level(logging.INFO, logger="quem_e_este_leao")
    quiz = generate_quiz(
        tmp_settings,
        difficulty=Difficulty.MEDIUM,
        player=player,
        allow_synthetic=False,
        output_dir=tmp_path,
    )
    assert not contains_identity(quiz.caption, player)
    assert not contains_identity(quiz.processed_image.name, player)
    for token in player.identity_tokens:
        if len(token) >= 4:
            assert token.casefold() not in quiz.caption.casefold()
            assert token.casefold() not in quiz.processed_image.name.casefold()

    exif = Image.open(quiz.processed_image).getexif()
    joined = " ".join(str(exif.get(k)) for k in exif.keys()) if exif else ""
    assert not contains_identity(joined, player)

    for rec in caplog.records:
        if rec.levelno >= logging.INFO:
            msg = rec.getMessage()
            assert player.display_name not in msg
            for token in player.nicknames:
                if len(token) >= 4:
                    assert token not in msg
