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
