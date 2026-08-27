"""Segunda passagem após a anonimização: cara residual + nome/número do jogador.

Texto de evento, patrocínio, publicidade, datas e estádios NÃO é fuga de
identidade e não rejeita o candidato.
"""

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

# 11th / 4TH / 1st — ordinais de evento, não número de camisola.
_ORDINAL = r"(?:st|nd|rd|th)"
_OCR_LANG = "eng+por"


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


@dataclass(frozen=True)
class OcrWord:
    text: str
    conf: float
    box: Box


def tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


def ocr_words(image_bgr: np.ndarray, *, psm: tuple[int, ...] = (6, 11)) -> list[OcrWord]:
    """Palavras OCR com caixa. Lista vazia se o Tesseract não estiver disponível."""
    if not tesseract_available():
        return []
    try:
        import pytesseract
        from pytesseract import Output
    except Exception:
        return []
    try:
        rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    except Exception:
        return []
    found: list[OcrWord] = []
    seen: set[tuple[int, int, int, int, str]] = set()
    for mode in psm:
        try:
            data = pytesseract.image_to_data(
                rgb,
                output_type=Output.DICT,
                lang=_OCR_LANG,
                config=f"--psm {mode}",
            )
        except Exception as exc:  # noqa: BLE001
            log.info("OCR indisponível (%s) — heurística apenas.", type(exc).__name__)
            continue
        n = len(data.get("text", []))
        for i in range(n):
            text = (data["text"][i] or "").strip()
            if not text:
                continue
            try:
                conf = float(data.get("conf", [-1])[i])
            except (IndexError, TypeError, ValueError):
                conf = -1.0
            if conf >= 0 and conf < 35:
                continue
            try:
                box = Box(
                    int(data["left"][i]),
                    int(data["top"][i]),
                    max(1, int(data["width"][i])),
                    max(1, int(data["height"][i])),
                )
            except (IndexError, TypeError, ValueError):
                continue
            key = (box.x, box.y, box.w, box.h, text)
            if key in seen:
                continue
            seen.add(key)
            found.append(OcrWord(text=text, conf=conf, box=box))
    return found


def ocr_full_text(image_bgr: np.ndarray) -> str:
    """Texto OCR completo (várias PSM). Vazio sem Tesseract."""
    if not tesseract_available():
        return ""
    try:
        import pytesseract
    except Exception:
        return ""
    try:
        rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
        a = pytesseract.image_to_string(rgb, lang=_OCR_LANG, config="--psm 6") or ""
        b = pytesseract.image_to_string(rgb, lang=_OCR_LANG, config="--psm 11") or ""
        extra = " ".join(w.text for w in ocr_words(image_bgr))
        return f"{a}\n{b}\n{extra}"
    except Exception as exc:  # noqa: BLE001
        log.info("OCR indisponível (%s) — heurística apenas.", type(exc).__name__)
        return ""


def _ocr_text(image_bgr: np.ndarray) -> str:
    return ocr_full_text(image_bgr)


def _heuristic_tokens(image_bgr: np.ndarray) -> str:
    """Sem Tesseract: não inventar texto; devolve vazio (a cara ainda é validada)."""
    return ""


def shirt_number_leaked(text: str, numbers: Sequence[int]) -> bool:
    """Número de camisola isolado. Não conta 11th, 4TH, anos (2014), etc."""
    if not numbers or not text:
        return False
    folded = _fold(text)
    for n in numbers:
        if n < 0 or n > 99:
            continue
        pattern = rf"(?<!\w){n}(?!(?:\d|{_ORDINAL}))"
        if re.search(pattern, folded, flags=re.IGNORECASE):
            return True
    return False


def identity_leaked(text: str, player: Player) -> bool:
    folded = _fold(text)
    for token in player.identity_tokens:
        t = _fold(token)
        if len(t) < 4:
            continue
        if re.search(rf"(?<!\w){re.escape(t)}(?!\w)", folded):
            return True
    return False


# Compat com chamadas internas / testes que usam o prefixo _.
_shirt_number_leaked = shirt_number_leaked
_identity_leaked = identity_leaked


def _token_is_player_number(token: str, numbers: Sequence[int] | None) -> bool:
    raw = token.strip().strip(".#:")
    if not raw:
        return False
    if re.fullmatch(rf"\d{{1,2}}{_ORDINAL}", raw, flags=re.IGNORECASE):
        return False
    if not re.fullmatch(r"\d{1,2}", raw):
        return False
    n = int(raw)
    if numbers is not None:
        return n in set(numbers)
    return 1 <= n <= 99


def _token_is_identity(token: str, player: Player | None) -> bool:
    if player is None:
        return False
    folded = _fold(token)
    if not folded:
        return False
    for t in player.identity_tokens:
        tt = _fold(t)
        if len(tt) < 4:
            continue
        if folded == tt or re.search(rf"(?<!\w){re.escape(tt)}(?!\w)", folded):
            return True
    return False


def _near(a: Box, b: Box, gap: int = 18) -> bool:
    ax2, ay2 = a.x + a.w, a.y + a.h
    bx2, by2 = b.x + b.w, b.y + b.h
    return not (ax2 + gap < b.x or bx2 + gap < a.x or ay2 + gap < b.y or by2 + gap < a.y)


def merge_boxes(boxes: Sequence[Box], iou_thresh: float = 0.12) -> list[Box]:
    if not boxes:
        return []
    remaining = list(boxes)
    merged: list[Box] = []
    while remaining:
        cur = remaining.pop(0)
        changed = True
        while changed:
            changed = False
            keep: list[Box] = []
            for other in remaining:
                if iou(cur, other) >= iou_thresh or _near(cur, other):
                    x1 = min(cur.x, other.x)
                    y1 = min(cur.y, other.y)
                    x2 = max(cur.x + cur.w, other.x + other.w)
                    y2 = max(cur.y + cur.h, other.y + other.h)
                    cur = Box(x1, y1, max(1, x2 - x1), max(1, y2 - y1))
                    changed = True
                else:
                    keep.append(other)
            remaining = keep
        merged.append(cur)
    return merged


def ocr_digit_words(image_bgr: np.ndarray) -> list[OcrWord]:
    """Passagem extra só com dígitos (números de camisola grandes)."""
    if not tesseract_available():
        return []
    try:
        import pytesseract
        from pytesseract import Output
    except Exception:
        return []
    try:
        rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    except Exception:
        return []
    h, w = rgb.shape[:2]
    if min(h, w) < 80:
        scale = 3
    elif min(h, w) < 160:
        scale = 2
    else:
        scale = 1
    if scale != 1:
        rgb = cv2.resize(rgb, (w * scale, h * scale), interpolation=cv2.INTER_CUBIC)
    found: list[OcrWord] = []
    cfg = "--psm {psm} -c tessedit_char_whitelist=0123456789"
    for mode in (8, 10, 11, 7):
        try:
            data = pytesseract.image_to_data(
                rgb, output_type=Output.DICT, config=cfg.format(psm=mode)
            )
        except Exception:
            continue
        n = len(data.get("text", []))
        for i in range(n):
            text = (data["text"][i] or "").strip()
            if not text:
                continue
            try:
                conf = float(data.get("conf", [-1])[i])
            except (IndexError, TypeError, ValueError):
                conf = -1.0
            if conf >= 0 and conf < 25:
                continue
            try:
                box = Box(
                    int(data["left"][i] / scale),
                    int(data["top"][i] / scale),
                    max(1, int(data["width"][i] / scale)),
                    max(1, int(data["height"][i] / scale)),
                )
            except (IndexError, TypeError, ValueError):
                continue
            found.append(OcrWord(text=text, conf=conf, box=box))
    return found


def identifying_boxes(
    image_bgr: np.ndarray,
    player: Player | None,
    *,
    pad: float = 0.22,
) -> list[Box]:
    """Caixas OCR cujo texto é o nome/alcunha ou o número da camisola.

    Patches de evento, patrocinadores, datas e estádios são ignorados.
    Sem jogador, só números isolados de 1–2 dígitos (típico de camisola).
    """
    h, w = image_bgr.shape[:2]
    numbers: Sequence[int] | None = player.shirt_numbers if player is not None else None
    boxes: list[Box] = []
    words = list(ocr_words(image_bgr)) + list(ocr_digit_words(image_bgr))
    for word in words:
        hit = _token_is_identity(word.text, player) or _token_is_player_number(word.text, numbers)
        if not hit:
            continue
        boxes.append(word.box.pad(pad, pad, w, h))
    return merge_boxes(boxes)


def validate_anonymized(
    image_bgr: np.ndarray,
    *,
    masked_boxes: Sequence[Box],
    player: Player | None = None,
    ocr_enabled: bool = True,
    abort_if_recognizable: bool = True,
) -> ValidationReport:
    """Rejeita se ainda houver cara visível, nome do jogador, ou número de camisola.

    Publicidade, logos de patrocínio, patches de evento, datas e nomes de
    estádio (ex.: MATCH AGAINST POVERTY) NÃO rejeitam o candidato.
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
            if identity_leaked(ocr_text, player):
                reasons.append("ocr_identity")
            if shirt_number_leaked(ocr_text, player.shirt_numbers):
                reasons.append("ocr_shirt_number")

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
