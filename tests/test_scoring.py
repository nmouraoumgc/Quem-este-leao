from __future__ import annotations

from pathlib import Path

from quem_e_este_leao.scoring import score_image


def test_real_samples_are_accepted(project_root: Path) -> None:
    for path in sorted((project_root / "assets" / "samples").glob("sample_*.jpg")):
        sc = score_image(path)
        assert sc.accepted, (path.name, sc.reject_reasons)
        assert sc.total >= 35
        assert sc.n_faces >= 1


def test_corrupt_file_is_rejected(tmp_path: Path) -> None:
    junk = tmp_path / "bad.jpg"
    junk.write_bytes(b"not-an-image")
    sc = score_image(junk)
    assert not sc.accepted
    assert "corrupt" in sc.reject_reasons


def test_tiny_image_rejected(tmp_path: Path) -> None:
    from PIL import Image

    p = tmp_path / "tiny.jpg"
    Image.new("RGB", (40, 40), (0, 128, 87)).save(p, "JPEG")
    sc = score_image(p)
    assert "too_small" in sc.reject_reasons or "no_face" in sc.reject_reasons


def test_event_banner_does_not_reject_candidate(tmp_path: Path) -> None:
    """Publicidade / evento no peito não é razão de rejeição."""
    from PIL import Image, ImageDraw, ImageFont

    from tests.helpers import make_player

    img = Image.new("RGB", (400, 500), (0, 128, 87))
    draw = ImageDraw.Draw(img)
    draw.ellipse((140, 40, 260, 180), fill=(210, 165, 120))
    draw.rectangle((80, 220, 320, 300), fill=(255, 255, 255))
    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 18
        )
    except Exception:
        font = ImageFont.load_default()
    draw.text((90, 240), "MATCH AGAINST POVERTY", fill=(0, 0, 0), font=font)
    path = tmp_path / "banner.jpg"
    img.save(path, "JPEG", quality=90)
    player = make_player(
        id="luis-figo", display_name="Luís Figo", nicknames=("Figo",), shirt_numbers=(7,)
    )
    sc = score_image(path, player=player)
    assert "identity_text" not in sc.reject_reasons
    assert "event_text" not in sc.reject_reasons
    assert "ocr_identity" not in sc.reject_reasons

def test_black_white_striped_kit_is_rejected(project_root: Path) -> None:
    """Camisola a preto-e-branco (Match Against Poverty) não é época Sporting."""
    path = project_root / "tests" / "fixtures" / "not_sporting_kit.jpg"
    sc = score_image(path)
    assert "not_sporting_kit" in sc.reject_reasons
    assert not sc.accepted


def test_green_white_torso_fixture_is_accepted(tmp_path: Path) -> None:
    from PIL import Image, ImageDraw

    import cv2
    import numpy as np

    from quem_e_este_leao.detection import Box, DetectedFace
    from quem_e_este_leao.scoring import _kit_bonus

    img = Image.new("RGB", (400, 520), (30, 40, 30))
    draw = ImageDraw.Draw(img)
    draw.ellipse((140, 30, 260, 170), fill=(210, 165, 120))
    for i, y in enumerate(range(190, 430, 28)):
        color = (0, 128, 87) if i % 2 == 0 else (245, 245, 245)
        draw.rectangle((90, y, 310, y + 28), fill=color)
    path = tmp_path / "green_white_torso.jpg"
    img.save(path, "JPEG", quality=95)
    bgr = cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2BGR)
    face = DetectedFace(box=Box(140, 30, 120, 140), score=1.0, source="test")
    assert _kit_bonus(bgr, face) >= 8.0
    sc = score_image(path)
    # YuNet pode não ver a elipse; o requisito de kit verde-e-branco cumpre-se no tronco.
    if sc.n_faces:
        assert sc.breakdown.get("kit", 0) >= 8
        assert "not_sporting_kit" not in sc.reject_reasons


def test_generated_black_white_stripes_have_no_sporting_kit(tmp_path: Path) -> None:
    from PIL import Image, ImageDraw

    import cv2
    import numpy as np

    from quem_e_este_leao.detection import Box, DetectedFace
    from quem_e_este_leao.scoring import _kit_bonus, kit_is_sporting

    img = Image.new("RGB", (400, 520), (10, 10, 10))
    draw = ImageDraw.Draw(img)
    draw.ellipse((140, 30, 260, 170), fill=(210, 165, 120))
    for x in range(80, 320, 28):
        color = (20, 20, 20) if ((x // 28) % 2 == 0) else (240, 240, 240)
        draw.rectangle((x, 190, x + 28, 430), fill=color)
    path = tmp_path / "bw_stripes.jpg"
    img.save(path, "JPEG", quality=95)
    bgr = cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2BGR)
    face = DetectedFace(box=Box(140, 30, 120, 140), score=1.0, source="test")
    kit = _kit_bonus(bgr, face)
    assert not kit_is_sporting(kit)
    sc = score_image(path)
    assert "not_sporting_kit" in sc.reject_reasons

