from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from quem_e_este_leao.config import Difficulty
from quem_e_este_leao.detection import detect_yunet
from quem_e_este_leao.processing import PARAMS, Box, anonymize, pixelate, sharpness
from quem_e_este_leao.validation import validate_anonymized


def _fixture(project_root: Path) -> tuple[Path, Box]:
    path = project_root / "tests" / "fixtures" / "synthetic_player.jpg"
    meta = json.loads((path.with_suffix(".json")).read_text())
    b = meta["face_box"]
    return path, Box(b["x"], b["y"], b["w"], b["h"])


def test_synthetic_face_becomes_unrecognizable(project_root: Path) -> None:
    path, face = _fixture(project_root)
    img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    original = sharpness(img, [face])
    r = anonymize(img, Difficulty.MEDIUM, forced_faces=[face], abort_if_recognizable=False)
    assert r.face_sharpness_after < original * 0.15
    h, w = img.shape[:2]
    ys = slice(int(h * 0.85), h)
    xs = slice(0, w)
    delta = np.mean(np.abs(img[ys, xs].astype(float) - r.image_bgr[ys, xs].astype(float)))
    assert delta < 12, "O terço inferior não devia ser pixelizado"


def test_no_geometry_fallback_without_face() -> None:
    from quem_e_este_leao.processing import AnonymizationError

    img = np.zeros((200, 200, 3), dtype=np.uint8)
    img[:] = (0, 128, 87)
    try:
        anonymize(img, Difficulty.MEDIUM, abort_if_recognizable=True)
        raise AssertionError("devia rejeitar")
    except AnonymizationError:
        pass


def test_padding_grows_with_difficulty() -> None:
    assert PARAMS[Difficulty.EASY].pad_y < PARAMS[Difficulty.HARD].pad_y
    assert PARAMS[Difficulty.EASY].face_expand < PARAMS[Difficulty.HARD].face_expand


def test_number_region_is_masked_on_fixture(project_root: Path) -> None:
    path, face = _fixture(project_root)
    img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    r = anonymize(img, Difficulty.MEDIUM, forced_faces=[face], abort_if_recognizable=False)
    assert r.extra_boxes, "MEDIUM deve mascarar a zona do número"
    chest = r.extra_boxes[0]
    before = sharpness(img, [chest])
    after = sharpness(r.image_bgr, [chest])
    if before > 5:
        assert after < before * 0.5


def test_real_sample_second_pass_ok(project_root: Path) -> None:
    path = project_root / "assets" / "samples" / "sample_01.jpg"
    img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    r = anonymize(img, Difficulty.MEDIUM, abort_if_recognizable=True)
    report = validate_anonymized(
        r.image_bgr,
        masked_boxes=r.face_boxes + r.extra_boxes,
        abort_if_recognizable=True,
    )
    assert report.ok, report.reasons
    leftover = detect_yunet(r.image_bgr, score_threshold=0.90)
    assert not leftover


def test_pixelate_still_works() -> None:
    img = np.zeros((120, 120, 3), dtype=np.uint8)
    img[20:90, 20:90] = (200, 170, 140)
    box = Box(20, 20, 70, 70)
    pixelate(img, box, 20)
    unique = len(np.unique(img[20:90, 20:90].reshape(-1, 3), axis=0))
    assert unique < 40
