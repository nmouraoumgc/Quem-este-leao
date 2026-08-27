from __future__ import annotations

from pathlib import Path

from PIL import Image

from quem_e_este_leao.config import Difficulty
from quem_e_este_leao.processing import Box, process_to_post, strip_exif_save


def _jpeg_with_exif(path: Path) -> Path:
    img = Image.new("RGB", (640, 800), (0, 128, 87))
    exif = img.getexif()
    # 270 = ImageDescription, 315 = Artist
    exif[270] = "Viktor Gyokerés — identidade de teste"
    exif[315] = "Fotógrafo Teste"
    img.save(path, format="JPEG", quality=90, exif=exif)
    return path


def test_exif_stripped_from_processed_image(tmp_path: Path) -> None:
    src = _jpeg_with_exif(tmp_path / "with_exif.jpg")
    original = Image.open(src)
    assert original.getexif().get(270) or original.info.get("exif")

    dest = tmp_path / "quiz_aabbccddeeff0011.jpg"
    process_to_post(
        src,
        dest,
        Difficulty.MEDIUM,
        abort_if_recognizable=False,
        forced_faces=[Box(200, 40, 240, 240)],
    )
    out = Image.open(dest)
    exif = out.getexif()
    # Pillow devolve um objecto vazio, sem tags identificadoras
    values = {exif.get(k) for k in exif.keys()} if exif else set()
    joined = " ".join(str(v) for v in values)
    assert "Gyoker" not in joined
    assert "Fotógrafo" not in joined
    assert "identidade" not in joined
    assert 270 not in exif
    assert 315 not in exif


def test_strip_exif_save_drops_description(tmp_path: Path) -> None:
    src = Image.new("RGB", (200, 200), (10, 80, 40))
    exif = src.getexif()
    exif[270] = "segredo"
    dirty = tmp_path / "dirty.jpg"
    src.save(dirty, format="JPEG", exif=exif)
    clean_path = tmp_path / "clean.jpg"
    loaded = Image.open(dirty)
    strip_exif_save(loaded, clean_path)
    again = Image.open(clean_path)
    assert 270 not in again.getexif()
