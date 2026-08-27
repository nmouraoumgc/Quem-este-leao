from __future__ import annotations

import numpy as np

from quem_e_este_leao.config import Difficulty
from quem_e_este_leao.images import generate_synthetic_kit_photo
from quem_e_este_leao.processing import PARAMS, Box, anonymize, pixelate, sharpness


def test_difficulty_changes_blur_strength(tmp_path) -> None:
    src = generate_synthetic_kit_photo(tmp_path / "kit.jpg").path
    import cv2

    data = np.fromfile(str(src), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    face = [Box(380, 210, 140, 190)]
    original = sharpness(image, face)
    after: dict[Difficulty, float] = {}
    for diff in Difficulty:
        r = anonymize(image, diff, forced_faces=face, abort_if_recognizable=False)
        after[diff] = r.face_sharpness_after
        assert r.face_sharpness_after < original * 0.1

    assert PARAMS[Difficulty.EASY].pixel_block < PARAMS[Difficulty.MEDIUM].pixel_block
    assert PARAMS[Difficulty.MEDIUM].pixel_block < PARAMS[Difficulty.HARD].pixel_block
    assert PARAMS[Difficulty.EASY].blur_ksize < PARAMS[Difficulty.MEDIUM].blur_ksize
    assert PARAMS[Difficulty.MEDIUM].blur_ksize < PARAMS[Difficulty.HARD].blur_ksize
    assert PARAMS[Difficulty.EASY].face_expand < PARAMS[Difficulty.HARD].face_expand
    # HARD esconde nome/número e detalhes extra; EASY não
    assert PARAMS[Difficulty.HARD].hide_name_number is True
    assert PARAMS[Difficulty.HARD].hide_extra is True
    assert PARAMS[Difficulty.EASY].hide_name_number is False
    assert original > 10  # a ROI de teste tem detalhe para anonimizar


def test_pixel_block_grows_with_difficulty() -> None:
    img = np.zeros((200, 200, 3), dtype=np.uint8)
    img[:, :] = (0, 180, 80)
    img[40:120, 40:120] = (200, 170, 140)
    box = Box(40, 40, 80, 80)
    easy = img.copy()
    hard = img.copy()
    pixelate(easy, box, PARAMS[Difficulty.EASY].pixel_block)
    pixelate(hard, box, PARAMS[Difficulty.HARD].pixel_block)
    # Mais pixelização ⇒ menos valores únicos na ROI
    easy_unique = len(np.unique(easy[40:120, 40:120].reshape(-1, 3), axis=0))
    hard_unique = len(np.unique(hard[40:120, 40:120].reshape(-1, 3), axis=0))
    assert hard_unique <= easy_unique
