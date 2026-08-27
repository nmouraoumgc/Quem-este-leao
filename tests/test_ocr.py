from __future__ import annotations

import shutil

import pytest

from quem_e_este_leao.validation import tesseract_available


pytestmark = pytest.mark.skipif(
    not tesseract_available() or shutil.which("tesseract") is None,
    reason="tesseract OCR não está instalado",
)


def test_ocr_rejects_readable_name(tmp_path) -> None:
    pytest.importorskip("pytesseract")
    from PIL import Image, ImageDraw, ImageFont

    from quem_e_este_leao.processing import Box
    from quem_e_este_leao.validation import validate_anonymized
    from tests.helpers import make_player

    img = Image.new("RGB", (400, 200), (0, 80, 40))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 36)
    except Exception:
        font = ImageFont.load_default()
    draw.text((20, 70), "Teste Leao", fill=(255, 255, 255), font=font)
    import numpy as np
    import cv2

    arr = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    player = make_player()
    report = validate_anonymized(
        arr, masked_boxes=[Box(0, 0, 10, 10)], player=player, ocr_enabled=True
    )
    assert not report.ok
    assert "ocr_identity" in report.reasons
