"""Pontuação de fotografias-candidatas. Preferir rejeitar a publicar uma cara identificável."""

from __future__ import annotations

import re
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

# Sporting green in OpenCV HSV (H 0-180). #008057 ≈ H 80, S alto.
# H até 90 / S>=70: exclui pretos com dominância ciano (ex. camisola Adidas a preto-e-branco).
GREEN_LO = np.array([45, 70, 40], dtype=np.uint8)
GREEN_HI = np.array([90, 255, 200], dtype=np.uint8)
WHITE_LO = np.array([0, 0, 180], dtype=np.uint8)
WHITE_HI = np.array([180, 50, 255], dtype=np.uint8)

# Produção: verde no tronco é requisito, não um bónus opcional.
SPORTING_KIT_HARD = 8.0  # g >= 8 % no peito
SPORTING_KIT_WEAK = 4.0  # verde residual; só com metadados Commons "Sporting CP"

_SPORTING_HINT = re.compile(
    r"sporting\s+c\.?\s*p\b|sporting\s+clube\s+de\s+portugal",
    re.IGNORECASE,
)
_HTML_TAG = re.compile(r"<[^>]+>")


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
        y1 = min(h, y0 + max(int(face.box.h * 1.25), 40))
        x0 = max(0, face.box.x + int(face.box.w * 0.08))
        x1 = min(w, face.box.x + face.box.w - int(face.box.w * 0.08))
        if x1 <= x0:
            x0, x1 = max(0, face.box.x), min(w, face.box.x + face.box.w)
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


def hint_says_sporting(text: str | None) -> bool:
    """Título/descrição Commons fala claramente em Sporting CP."""
    if not text:
        return False
    plain = _HTML_TAG.sub(" ", text)
    return bool(_SPORTING_HINT.search(plain))


def kit_is_sporting(
    kit_score: float,
    *,
    commons_hint: str | None = None,
) -> bool:
    """Verde no tronco é obrigatório. Metadados Commons só ajudam se o detector for fraco."""
    if kit_score <= 0.0:
        return False
    if kit_score >= SPORTING_KIT_HARD:
        return True
    if kit_score >= SPORTING_KIT_WEAK and hint_says_sporting(commons_hint):
        return True
    return False


def score_image(
    path: Path,
    *,
    model_path: Path | None = None,
    min_side: int = 240,
    player=None,
    require_sporting_kit: bool = True,
    commons_hint: str | None = None,
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
        if require_sporting_kit and not kit_is_sporting(kit, commons_hint=commons_hint):
            reasons.append("not_sporting_kit")
    else:
        breakdown["face_detected"] = 0.0
        if require_sporting_kit:
            reasons.append("not_sporting_kit")

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

    # Nome/número do jogador: penaliza (preferir foto limpa) mas NÃO rejeita —
    # o processamento ainda pode tapar. Evento/patrocínio/publicidade: sem penalização extra.
    if player is not None:
        try:
            from quem_e_este_leao.validation import (
                identity_leaked,
                ocr_full_text,
                shirt_number_leaked,
                tesseract_available,
            )

            if tesseract_available():
                ocr = ocr_full_text(img)
                if ocr and identity_leaked(ocr, player):
                    breakdown["identity_text"] = -10.0
                    total -= 10.0
                if ocr and shirt_number_leaked(ocr, player.shirt_numbers):
                    breakdown["shirt_number"] = -4.0
                    total -= 4.0
        except Exception:  # noqa: BLE001
            pass

    return ImageScore(
        total=float(total),
        breakdown=breakdown,
        reject_reasons=reasons,
        faces=faces,
        width=w,
        height=h,
    )


def _commons_hint_from_meta(meta: object) -> str | None:
    attr = getattr(meta, "attribution", None)
    if not isinstance(attr, dict):
        return None
    parts = [str(v) for v in attr.values() if v]
    return " ".join(parts) if parts else None


def rank_candidates(
    paths_and_meta: list[tuple[Path, object]],
    *,
    model_path: Path | None = None,
    min_score: float = 35.0,
    player=None,
    require_sporting_kit: bool = True,
) -> list[tuple[object, ImageScore]]:
    """Ordena candidatos aceites (melhor primeiro). Rejeitados ficam de fora."""
    ranked: list[tuple[object, ImageScore]] = []
    for path, meta in paths_and_meta:
        sc = score_image(
            path,
            model_path=model_path,
            player=player,
            require_sporting_kit=require_sporting_kit,
            commons_hint=_commons_hint_from_meta(meta),
        )
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
