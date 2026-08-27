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
