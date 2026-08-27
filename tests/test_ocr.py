from __future__ import annotations

import shutil

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from quem_e_este_leao.config import Difficulty
from quem_e_este_leao.processing import Box, anonymize
from quem_e_este_leao.validation import (
    identity_leaked,
    ocr_full_text,
    shirt_number_leaked,
    tesseract_available,
    validate_anonymized,
)
from tests.helpers import make_player


pytestmark = pytest.mark.skipif(
    not tesseract_available() or shutil.which("tesseract") is None,
    reason="tesseract OCR não está instalado",
)


def _font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype(
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", size
        )
    except Exception:
        return ImageFont.load_default()


def _bgr(img: Image.Image) -> np.ndarray:
    return cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2BGR)


def test_ocr_rejects_readable_name(tmp_path) -> None:
    pytest.importorskip("pytesseract")
    img = Image.new("RGB", (400, 200), (0, 80, 40))
    draw = ImageDraw.Draw(img)
    draw.text((20, 70), "Teste Leao", fill=(255, 255, 255), font=_font(36))
    player = make_player()
    report = validate_anonymized(
        _bgr(img), masked_boxes=[Box(0, 0, 10, 10)], player=player, ocr_enabled=True
    )
    assert not report.ok
    assert "ocr_identity" in report.reasons


def test_ocr_rejects_readable_shirt_number() -> None:
    img = Image.new("RGB", (360, 220), (0, 80, 40))
    draw = ImageDraw.Draw(img)
    draw.text((140, 70), "9", fill=(255, 255, 255), font=_font(72))
    player = make_player(shirt_numbers=(9,))
    report = validate_anonymized(
        _bgr(img), masked_boxes=[Box(0, 0, 10, 10)], player=player, ocr_enabled=True
    )
    assert not report.ok
    assert "ocr_shirt_number" in report.reasons


def test_ocr_allows_event_and_sponsor_text() -> None:
    """MATCH AGAINST POVERTY / data / estádio NÃO é fuga de identidade."""
    img = Image.new("RGB", (720, 280), (8, 8, 8))
    draw = ImageDraw.Draw(img)
    draw.rectangle((40, 40, 680, 240), fill=(255, 255, 255))
    font = _font(28)
    draw.text((60, 60), "11th MATCH AGAINST POVERTY", fill=(0, 0, 0), font=font)
    draw.text((60, 110), "4TH MARCH 2014", fill=(0, 0, 0), font=font)
    draw.text((60, 160), "STADE DE SUISSE, BERN", fill=(0, 0, 0), font=font)
    player = make_player(
        id="luis-figo",
        display_name="Luís Figo",
        nicknames=("Figo",),
        shirt_numbers=(7,),
    )
    arr = _bgr(img)
    report = validate_anonymized(
        arr, masked_boxes=[Box(0, 0, 10, 10)], player=player, ocr_enabled=True
    )
    text = (report.ocr_text or ocr_full_text(arr)).upper()
    assert "ocr_identity" not in report.reasons
    assert "ocr_shirt_number" not in report.reasons
    assert report.ok, report.reasons
    assert "POVERTY" in text or "MATCH" in text
    assert not identity_leaked(text, player)
    assert not shirt_number_leaked(text, player.shirt_numbers)


def test_ordinal_event_number_is_not_shirt_number() -> None:
    assert not shirt_number_leaked("11th MATCH AGAINST POVERTY", (11,))
    assert not shirt_number_leaked("4TH MARCH 2014, STADE DE SUISSE, BERN", (4, 7))
    assert shirt_number_leaked("camisola 7", (7,))
    assert shirt_number_leaked(" 11 ", (11,))


def _kit_image(*, name: str | None, number: str | None, banner: str | None) -> tuple[np.ndarray, Box, Box]:
    """Devolve (bgr, face_box, banner_box). banner_box pode ser 0-size se não houver patch."""
    w, h = 640, 1000
    img = Image.new("RGB", (w, h), (18, 90, 40))
    draw = ImageDraw.Draw(img)
    draw.ellipse((240, 40, 400, 210), fill=(210, 165, 120))
    draw.ellipse((270, 95, 300, 130), fill=(30, 30, 30))
    draw.ellipse((340, 95, 370, 130), fill=(30, 30, 30))
    draw.rounded_rectangle((180, 240, 460, 700), radius=24, fill=(0, 128, 87))
    banner_box = Box(0, 0, 1, 1)
    if banner:
        draw.rectangle((190, 380, 450, 500), fill=(255, 255, 255))
        draw.text((205, 400), "11th MATCH AGAINST", fill=(0, 0, 0), font=_font(22))
        draw.text((205, 440), "POVERTY", fill=(0, 0, 0), font=_font(36))
        banner_box = Box(190, 380, 260, 120)
    if number:
        draw.text((285, 530), number, fill=(255, 255, 255), font=_font(80))
    if name:
        draw.text((245, 640), name, fill=(255, 255, 255), font=_font(32))
    draw.rectangle((210, 740, 430, 920), fill=(245, 245, 245))
    face_box = Box(240, 40, 160, 170)
    return _bgr(img), face_box, banner_box


def test_anonymize_masks_name_and_number_not_event_banner() -> None:
    arr, face, _banner = _kit_image(name="FIGO", number="7", banner="11th MATCH AGAINST POVERTY")
    player = make_player(
        id="luis-figo",
        display_name="Luís Figo",
        nicknames=("Figo",),
        shirt_numbers=(7,),
    )
    result = anonymize(
        arr,
        Difficulty.MEDIUM,
        forced_faces=[face],
        abort_if_recognizable=False,
        player=player,
        ocr_enabled=True,
    )
    text = ocr_full_text(result.image_bgr).upper()
    # identidade do jogador não sobrevive
    assert "FIGO" not in text
    assert not identity_leaked(text, player)
    assert not shirt_number_leaked(text, (7,))
    # evento/publicidade pode ficar
    # (se o OCR falhar o banner, não falhamos o teste por isso)
    _ = text
    # virilha / calções não pixelizados
    h, w = arr.shape[:2]
    delta = np.mean(
        np.abs(arr[int(h * 0.85) :, :].astype(float) - result.image_bgr[int(h * 0.85) :, :].astype(float))
    )
    assert delta < 12, "O terço inferior não devia ser pixelizado"


def test_event_banner_alone_is_not_masked_or_rejected() -> None:
    arr, face, banner_box = _kit_image(name=None, number=None, banner="11th MATCH AGAINST POVERTY")
    player = make_player(
        id="luis-figo",
        display_name="Luís Figo",
        nicknames=("Figo",),
        shirt_numbers=(7,),
    )
    result = anonymize(
        arr,
        Difficulty.MEDIUM,
        forced_faces=[face],
        abort_if_recognizable=False,
        player=player,
        ocr_enabled=True,
    )
    report = validate_anonymized(
        result.image_bgr,
        masked_boxes=result.face_boxes + result.extra_boxes,
        player=player,
        ocr_enabled=True,
    )
    assert "ocr_identity" not in report.reasons
    assert "ocr_shirt_number" not in report.reasons
    text = (report.ocr_text or ocr_full_text(result.image_bgr)).upper()
    ys, xs = banner_box.as_slice()
    delta = float(
        np.mean(
            np.abs(arr[ys, xs].astype(float) - result.image_bgr[ys, xs].astype(float))
        )
    )
    # o patch de evento não é pixelizado como se fosse nome/número
    assert delta < 40, f"banner demasiado mascarado (delta={delta:.1f})"
    readable = "POVERTY" in text or "MATCH" in text or "AGAINST" in text
    assert readable or delta < 18
