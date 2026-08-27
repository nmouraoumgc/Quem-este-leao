"""Segunda passagem após a anonimização: cara residual + texto identificador."""

from __future__ import annotations

import re
import shutil
import unicodedata
from dataclasses import dataclass, field
from typing import Sequence

import cv2
import numpy as np

from quem_e_este_leao.detection import Box, detect_faces_scored, iou
from quem_e_este_leao.logging_setup import get_logger
from quem_e_este_leao.players import Player

log = get_logger("validation")

# Confiança acima da qual uma cara «ainda visível» rejeita o output.
RESIDUAL_FACE_SCORE = 0.90
UNMASKED_FACE_SCORE = 0.70


def _fold(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch)).casefold()


@dataclass
class ValidationReport:
    ok: bool
    reasons: list[str] = field(default_factory=list)
    residual_faces: int = 0
    ocr_text: str = ""

    @property
    def reason(self) -> str:
        return "; ".join(self.reasons) if self.reasons else "ok"


def tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


def _ocr_text(image_bgr: np.ndarray) -> str:
    if not tesseract_available():
        return ""
    try:
        import pytesseract
    except Exception:
        return ""
    try:
        rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
        # psm 6 = bloco uniforme; também tentamos 11 (sparse)
        a = pytesseract.image_to_string(rgb, config="--psm 6") or ""
        b = pytesseract.image_to_string(rgb, config="--psm 11") or ""
        return f"{a}\n{b}"
    except Exception as exc:  # noqa: BLE001
        log.info("OCR indisponível (%s) — heurística apenas.", type(exc).__name__)
        return ""


def _heuristic_tokens(image_bgr: np.ndarray) -> str:
    """Sem Tesseract: não inventar texto; devolve vazio (a cara ainda é validada)."""
    return ""


def _shirt_number_leaked(text: str, numbers: Sequence[int]) -> bool:
    folded = text
    for n in numbers:
        # 1–2 dígitos isolados iguais ao número da camisola
        if re.search(rf"(?<!\d){n}(?!\d)", folded):
            return True
    return False


def _identity_leaked(text: str, player: Player) -> bool:
    folded = _fold(text)
    for token in player.identity_tokens:
        t = _fold(token)
        if len(t) < 4:
            continue
        if re.search(rf"(?<!\w){re.escape(t)}(?!\w)", folded):
            return True
    return False


def validate_anonymized(
    image_bgr: np.ndarray,
    *,
    masked_boxes: Sequence[Box],
    player: Player | None = None,
    ocr_enabled: bool = True,
    abort_if_recognizable: bool = True,
) -> ValidationReport:
    """Rejeita se ainda houver cara visível fora (ou com alta confiança dentro) das máscaras.

    Também rejeita se o OCR (quando disponível) ler o nome/alcunha ou o número.
    """
    reasons: list[str] = []
    h, w = image_bgr.shape[:2]
    img_area = float(h * w) or 1.0
    faces = detect_faces_scored(image_bgr, try_rotations=False, score_threshold=0.55)
    residual = 0
    for face in faces:
        # caras minúsculas de fundo: ignorar salvo confiança extrema
        tiny = face.box.area / img_area < 0.012
        overlaps = any(iou(face.box, m) >= 0.20 for m in masked_boxes) if masked_boxes else False
        if tiny and face.score < 0.88:
            continue
        if not overlaps and face.score >= UNMASKED_FACE_SCORE:
            residual += 1
            reasons.append("face_unmasked")
        elif overlaps and face.score >= RESIDUAL_FACE_SCORE:
            residual += 1
            reasons.append("face_still_confident")
        elif not masked_boxes and face.score >= RESIDUAL_FACE_SCORE:
            residual += 1
            reasons.append("face_overall")

    ocr_text = ""
    if ocr_enabled and player is not None:
        ocr_text = _ocr_text(image_bgr) if tesseract_available() else _heuristic_tokens(image_bgr)
        if ocr_text:
            if _identity_leaked(ocr_text, player):
                reasons.append("ocr_identity")
            if _shirt_number_leaked(ocr_text, player.shirt_numbers):
                reasons.append("ocr_shirt_number")

    # dedup reasons
    uniq: list[str] = []
    for r in reasons:
        if r not in uniq:
            uniq.append(r)

    ok = True
    if abort_if_recognizable and uniq:
        ok = False
        log.info("Segunda passagem REJEITOU: %s", ", ".join(uniq))
    elif uniq:
        log.info("Segunda passagem avisos (não aborta): %s", ", ".join(uniq))
    else:
        log.info("Segunda passagem: sem fugas detectadas (caras residuais=%s).", residual)

    return ValidationReport(ok=ok, reasons=uniq, residual_faces=residual, ocr_text=ocr_text[:500])
