from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from quem_e_este_leao.detection import detect_faces_scored, detect_yunet


def test_yunet_detects_real_sample_faces(project_root: Path) -> None:
    samples = sorted((project_root / "assets" / "samples").glob("sample_*.jpg"))
    assert samples
    detected = 0
    for path in samples:
        img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
        faces = detect_yunet(img)
        if faces:
            detected += 1
            assert faces[0].score >= 0.55
            assert faces[0].box.w >= 24
    assert detected == len(samples)


def test_rotated_sample_still_finds_a_face(project_root: Path) -> None:
    path = project_root / "assets" / "samples" / "sample_01.jpg"
    img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    h, w = img.shape[:2]
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), 18, 1.0)
    rotated = cv2.warpAffine(img, matrix, (w, h))
    faces = detect_faces_scored(rotated, try_rotations=True)
    assert faces, "Esperava uma cara mesmo com a fotografia rodada."
