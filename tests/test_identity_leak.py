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


def test_output_ocr_must_not_contain_player_name(project_root, tmp_path) -> None:
    """Nome/número do jogador não sobrevivem; texto de evento pode ficar."""
    import shutil

    import cv2
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont

    from quem_e_este_leao.processing import Box, anonymize
    from quem_e_este_leao.validation import (
        identity_leaked,
        ocr_full_text,
        shirt_number_leaked,
        tesseract_available,
    )
    from tests.helpers import make_player

    if not tesseract_available() or shutil.which("tesseract") is None:
        return

    img = Image.new("RGB", (640, 800), (10, 70, 30))
    draw = ImageDraw.Draw(img)
    try:
        font_big = ImageFont.truetype(
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 40
        )
        font_num = ImageFont.truetype(
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 72
        )
        font_sm = ImageFont.truetype(
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 22
        )
    except Exception:
        font_big = font_num = font_sm = ImageFont.load_default()
    draw.ellipse((240, 60, 400, 240), fill=(210, 165, 120))
    draw.rounded_rectangle((180, 250, 460, 600), radius=20, fill=(0, 128, 87))
    draw.rectangle((200, 280, 440, 370), fill=(255, 255, 255))
    draw.text((210, 295), "MATCH AGAINST", fill=(0, 0, 0), font=font_sm)
    draw.text((210, 325), "POVERTY", fill=(0, 0, 0), font=font_sm)
    draw.text((250, 400), "FIGO", fill=(255, 255, 255), font=font_big)
    draw.text((300, 470), "7", fill=(255, 255, 255), font=font_num)
    arr = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    player = make_player(
        id="luis-figo",
        display_name="Luís Figo",
        nicknames=("Figo",),
        shirt_numbers=(7,),
    )
    result = anonymize(
        arr,
        Difficulty.MEDIUM,
        forced_faces=[Box(240, 60, 160, 180)],
        abort_if_recognizable=False,
        player=player,
        ocr_enabled=True,
    )
    text = ocr_full_text(result.image_bgr)
    assert not identity_leaked(text, player), text
    assert not shirt_number_leaked(text, player.shirt_numbers), text
    # evento permitido
    # (não exigimos que sobreviva, só que não cause falha acima)
    _ = tmp_path
