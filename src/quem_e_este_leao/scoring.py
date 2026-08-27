"""Pontuação de fotografias-candidatas. Preferir rejeitar a publicar uma cara identificável."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from quem_e_este_leao.detection import (
    DetectedFace,
    detect_faces_scored,
    dominant_face,
)
from quem_e_este_leao.logging_setup import get_logger

log = get_logger("scoring")

# Sporting green in OpenCV HSV (H 0-180). #008057 ≈ H 75.
GREEN_LO = np.array([40, 40, 40], dtype=np.uint8)
GREEN_HI = np.array([95, 255, 220], dtype=np.uint8)
WHITE_LO = np.array([0, 0, 180], dtype=np.uint8)
WHITE_HI = np.array([180, 50, 255], dtype=np.uint8)


@dataclass
class ImageScore:
    total: float
    breakdown: dict[str, float] = field(default_factory=dict)
    reject_reasons: list[str] = field(default_factory=list)
    faces: list[DetectedFace] = field(default_factory=list)
    width: int = 0
    height: int = 0

    @property
    def accepted(self) -> bool:
        return not self.reject_reasons

    @property
    def n_faces(self) -> int:
        return len(self.faces)


def _decode(path: Path) -> np.ndarray | None:
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
        if data.size < 32:
            return None
        img = cv2.imdecode(data, cv2.IMREAD_COLOR)
        return img
    except Exception:  # noqa: BLE001
        return None


def _textish_ratio(gray: np.ndarray) -> float:
    """Heurística: densidade de contornos «tipo texto» (sem OCR)."""
    if gray.size < 400:
        return 0.0
    try:
        blur = cv2.GaussianBlur(gray, (3, 3), 0)
        edges = cv2.Canny(blur, 60, 160)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 3))
        closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)
        contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        h, w = gray.shape[:2]
        area = float(h * w) or 1.0
        text_area = 0.0
        for c in contours:
            x, y, cw, ch = cv2.boundingRect(c)
            if cw < 8 or ch < 8:
                continue
            aspect = cw / max(ch, 1)
            if 1.2 <= aspect <= 12 and 8 <= ch <= h * 0.18:
                text_area += cw * ch
        return text_area / area
    except Exception:  # noqa: BLE001
        return 0.0


def _kit_bonus(bgr: np.ndarray, face: DetectedFace | None) -> float:
    h, w = bgr.shape[:2]
    if face is None:
        torso = bgr[int(h * 0.35) : int(h * 0.75), int(w * 0.2) : int(w * 0.8)]
    else:
        y0 = min(h - 1, face.box.y + face.box.h)
        y1 = min(h, y0 + max(int(face.box.h * 1.6), 40))
        x0 = max(0, face.box.x - int(face.box.w * 0.2))
        x1 = min(w, face.box.x + face.box.w + int(face.box.w * 0.2))
        torso = bgr[y0:y1, x0:x1]
    if torso.size < 50:
        return 0.0
    hsv = cv2.cvtColor(torso, cv2.COLOR_BGR2HSV)
    green = cv2.inRange(hsv, GREEN_LO, GREEN_HI)
    white = cv2.inRange(hsv, WHITE_LO, WHITE_HI)
    n = float(torso.shape[0] * torso.shape[1]) or 1.0
    g, wh = float(np.count_nonzero(green)) / n, float(np.count_nonzero(white)) / n
    score = 0.0
    if g >= 0.08:
        score += 8.0
    if wh >= 0.05 and g >= 0.05:
        score += 6.0
    elif g >= 0.18:
        score += 4.0
    return score


def score_image(
    path: Path,
    *,
    model_path: Path | None = None,
    min_side: int = 240,
) -> ImageScore:
    img = _decode(path)
    if img is None:
        return ImageScore(total=0.0, reject_reasons=["corrupt"])
    h, w = img.shape[:2]
    breakdown: dict[str, float] = {}
    reasons: list[str] = []

    if min(h, w) < min_side:
        reasons.append("too_small")

    faces = detect_faces_scored(img, model_path=model_path, try_rotations=True)
    if not faces:
        reasons.append("no_face")

    total = 0.0
    # resolução
    res = float(min(max(min(h, w) - min_side, 0), 800)) / 40.0  # 0–20
    breakdown["resolution"] = res
    total += res

    if faces:
        breakdown["face_detected"] = 25.0
        total += 25.0
        img_area = float(h * w) or 1.0
        dom = dominant_face(faces)
        assert dom is not None
        frac = dom.box.area / img_area
        if frac < 0.006:
            reasons.append("tiny_face")
            breakdown["face_size"] = -20.0
            total -= 20.0
        elif frac < 0.015:
            breakdown["face_size"] = 2.0
            total += 2.0
        elif frac <= 0.45:
            breakdown["face_size"] = 15.0
            total += 15.0
        else:
            # close-up: still usable
            breakdown["face_size"] = 10.0
            total += 10.0

        if min(dom.box.w, dom.box.h) < 24:
            reasons.append("impossible_anonymization")

        # crop: cara no terço superior / meio
        if dom.box.cy <= h * 0.62:
            breakdown["crop"] = 8.0
            total += 8.0
        else:
            breakdown["crop"] = 0.0

        # jogadores extra
        others = [f for f in faces if f is not dom]
        significant_others = [
            f for f in others if f.box.area >= dom.box.area * 0.35 and f.score >= 0.7
        ]
        if len(faces) == 1 or not significant_others:
            breakdown["single_player"] = 10.0
            total += 10.0
        elif len(significant_others) == 1:
            breakdown["single_player"] = -8.0
            total -= 8.0
        else:
            reasons.append("multi_player")
            breakdown["single_player"] = -20.0
            total -= 20.0

        kit = _kit_bonus(img, dom)
        breakdown["kit"] = kit
        total += kit
    else:
        breakdown["face_detected"] = 0.0

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    text_ratio = _textish_ratio(gray)
    if text_ratio > 0.22:
        reasons.append("excessive_text")
        breakdown["text"] = -18.0
        total -= 18.0
    elif text_ratio > 0.10:
        breakdown["text"] = -8.0
        total -= 8.0
    elif text_ratio > 0.05:
        breakdown["text"] = -3.0
        total -= 3.0
    else:
        breakdown["text"] = 0.0

    return ImageScore(
        total=float(total),
        breakdown=breakdown,
        reject_reasons=reasons,
        faces=faces,
        width=w,
        height=h,
    )


def rank_candidates(
    paths_and_meta: list[tuple[Path, object]],
    *,
    model_path: Path | None = None,
    min_score: float = 35.0,
) -> list[tuple[object, ImageScore]]:
    """Ordena candidatos aceites (melhor primeiro). Rejeitados ficam de fora."""
    ranked: list[tuple[object, ImageScore]] = []
    for path, meta in paths_and_meta:
        sc = score_image(path, model_path=model_path)
        log.info(
            "Candidato %s: score=%.1f reject=%s",
            path.name,
            sc.total,
            ",".join(sc.reject_reasons) or "-",
        )
        if sc.accepted and sc.total >= min_score:
            ranked.append((meta, sc))
    ranked.sort(key=lambda it: it[1].total, reverse=True)
    return ranked
