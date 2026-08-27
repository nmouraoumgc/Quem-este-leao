"""Anonimização (cara / nome / número) e composição 1080×1080 com branding Sporting."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from pathlib import Path
from typing import Iterable, Sequence

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from quem_e_este_leao.config import Difficulty
from quem_e_este_leao.detection import Box, DetectedFace, detect_faces, detect_faces_scored
from quem_e_este_leao.logging_setup import get_logger

log = get_logger("processing")

CANVAS = 1080
# Verde Sporting #008057
SPORTING_GREEN = (0, 128, 87)
DARK_GREEN = (6, 28, 20)
WHITE = (255, 255, 255)
OFF_WHITE = (246, 248, 246)
GOLD = (201, 168, 76)

FONT_BOLD = Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf")
FONT_REG = Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf")
FONT_FALLBACK = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")

HEADER_H = 72
FOOTER_H = 148
SIDE = 28
GAP = 14


class AnonymizationError(RuntimeError):
    """A fotografia continua reconhecível — abortar o candidato."""


# Re-export for callers / tests that import Box from processing.
__all__ = [
    "AnonymizationError",
    "AnonymizeResult",
    "Box",
    "DifficultyParams",
    "PARAMS",
    "anonymize",
    "compose_frame",
    "detect_faces",
    "opaque_filename",
    "pixelate",
    "process_to_post",
    "sharpness",
    "strip_exif_save",
    "try_ocr_boxes",
    "detect_number_like_boxes",
    "number_from_face",
    "torso_has_wide_banner",
]


@dataclass(frozen=True)
class DifficultyParams:
    pixel_block: int
    blur_ksize: int
    face_expand: float
    pad_x: float
    pad_y: float
    hide_name_number: bool
    hide_extra: bool
    min_sharpness_ratio: float


PARAMS: dict[Difficulty, DifficultyParams] = {
    # easy = moderado; medium = forte; hard = extremo
    # pad_* é fracção da caixa ORIGINAL (cabelo/queixo), não da já expandida.
    Difficulty.EASY: DifficultyParams(22, 45, 1.22, 0.12, 0.20, False, False, 0.45),
    Difficulty.MEDIUM: DifficultyParams(36, 81, 1.38, 0.16, 0.28, True, False, 0.22),
    Difficulty.HARD: DifficultyParams(52, 111, 1.55, 0.22, 0.36, True, True, 0.12),
}


@dataclass
class AnonymizeResult:
    image_bgr: np.ndarray
    face_boxes: list[Box]
    extra_boxes: list[Box]
    used_fallback: bool
    face_sharpness_before: float
    face_sharpness_after: float
    detected: list[DetectedFace] = field(default_factory=list)


def _font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    for candidate in (path, FONT_BOLD, FONT_FALLBACK):
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def geometry_fallback(height: int, width: int) -> tuple[Box, Box]:
    """Mantido só para testes / diagnóstico — NÃO se usa em produção."""
    face = Box(int(width * 0.18), int(height * 0.02), int(width * 0.64), int(height * 0.35))
    chest = Box(int(width * 0.28), int(height * 0.38), int(width * 0.44), int(height * 0.28))
    return face.clip(width, height), chest.clip(width, height)


def chest_from_face(face: Box, width: int, height: int) -> Box:
    """Zona larga do peito — diagnóstico apenas. Em produção usamos número compacto + OCR.

    Não deve ser aplicada às calças / virilha nem a patches de evento.
    """
    y = face.y + int(face.h * 0.32)
    h = max(int(face.h * 1.05), 28)
    x = face.x - int(face.w * 0.55)
    w = max(int(face.w * 2.05), 28)
    return Box(x, y, w, h).clip(width, height)


def number_from_face(face: Box, width: int, height: int) -> Box:
    """Caixa compacta do número de camisola (centro do peito), não um banner largo."""
    nw = max(int(face.w * 0.58), 22)
    nh = max(int(face.h * 0.52), 22)
    x = int(face.x + face.w / 2 - nw / 2)
    y = face.y + int(face.h * 0.90)
    return Box(x, y, nw, nh).clip(width, height)


def _torso_roi(face: Box, width: int, height: int) -> Box:
    """Peito/abdomen alto — pára antes das calças / virilha; não inclui mangas."""
    y0 = min(height - 1, face.y + int(face.h * 0.85))
    y1 = min(int(height * 0.72), face.y + int(face.h * 3.1), height)
    x0 = max(0, face.x - int(face.w * 0.22))
    x1 = min(width, face.x + face.w + int(face.w * 0.22))
    if y1 <= y0:
        y1 = min(height, y0 + max(24, int(face.h * 0.8)))
    return Box(x0, y0, max(1, x1 - x0), max(1, y1 - y0)).clip(width, height)


def torso_has_wide_banner(image_bgr: np.ndarray, faces: Sequence[Box]) -> bool:
    """Patch rectangular largo no peito (evento/patrocínio) — NÃO se mascara."""
    h, w = image_bgr.shape[:2]
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY) if image_bgr.ndim == 3 else image_bgr
    for face in faces:
        roi_box = _torso_roi(face, w, h)
        ys, xs = roi_box.as_slice()
        roi = gray[ys, xs]
        if roi.size < 400:
            continue
        blur = cv2.GaussianBlur(roi, (5, 5), 0)
        edges = cv2.Canny(blur, 50, 140)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 3))
        closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)
        contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        roi_area = float(roi_box.area) or 1.0
        for c in contours:
            bx, by, bw, bh = cv2.boundingRect(c)
            if bw < 24 or bh < 10:
                continue
            aspect = bw / max(bh, 1)
            frac = (bw * bh) / roi_area
            if aspect >= 2.0 and frac >= 0.05:
                return True
    return False


def detect_number_like_boxes(image_bgr: np.ndarray, faces: Sequence[Box]) -> list[Box]:
    """Blobs compactos de alto contraste tipo 1–2 dígitos no peito.

    Letras de um banner (evento / publicidade) são pequenas e em fila — ignora-as.
    Não desce à virilha.
    """
    h, w = image_bgr.shape[:2]
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY) if image_bgr.ndim == 3 else image_bgr
    out: list[Box] = []
    for face in faces:
        roi_box = _torso_roi(face, w, h)
        ys, xs = roi_box.as_slice()
        roi = gray[ys, xs]
        if roi.size < 100:
            continue
        blur = cv2.GaussianBlur(roi, (5, 5), 0)
        thr = cv2.adaptiveThreshold(
            blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 21, 5
        )
        variants = [thr, cv2.bitwise_not(thr)]
        roi_h, roi_w = roi.shape[:2]
        roi_area = float(roi_h * roi_w) or 1.0
        chin = face.y + face.h
        raw: list[Box] = []
        seen: set[tuple[int, int, int, int]] = set()
        for binary in variants:
            contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for c in contours:
                bx, by, bw, bh = cv2.boundingRect(c)
                if bh < 12 or bw < 6:
                    continue
                aspect = bw / max(bh, 1)
                if aspect > 2.15 or aspect < 0.22:
                    continue
                # números de camisola ~ fracção da cara; letras de patch são bem menores
                if bh < face.h * 0.20 or bh > face.h * 0.95:
                    continue
                # o tronco inteiro / jersey não é um número
                if bw > roi_w * 0.70 or bw > face.w * 1.35:
                    continue
                if (bw * bh) / roi_area > 0.28:
                    continue
                abs_box = Box(roi_box.x + bx, roi_box.y + by, bw, bh)
                cy = abs_box.y + abs_box.h / 2
                if cy < chin + face.h * 0.08:
                    continue
                key = (bx // 4, by // 4, bw // 4, bh // 4)
                if key in seen:
                    continue
                seen.add(key)
                raw.append(abs_box)
        kept = _drop_text_rows(raw)
        for box in kept:
            padded = box.pad(0.22, 0.16, w, h)
            if _sane_extra_box(padded, w, h):
                out.append(padded)
    return out


def _drop_text_rows(boxes: Sequence[Box]) -> list[Box]:
    """3+ blobs alinhados horizontalmente = linha de texto, não número."""
    remaining = list(boxes)
    kept: list[Box] = []
    while remaining:
        seed = remaining.pop(0)
        row = [seed]
        rest: list[Box] = []
        for other in remaining:
            overlap = min(seed.y + seed.h, other.y + other.h) - max(seed.y, other.y)
            if overlap >= 0.45 * min(seed.h, other.h):
                row.append(other)
            else:
                rest.append(other)
        remaining = rest
        if len(row) >= 3:
            continue
        kept.extend(row)
    return kept


def _sane_extra_box(box: Box, width: int, height: int) -> bool:
    area = box.area
    img_area = float(width * height) or 1.0
    if area < 40:
        return False
    if area / img_area > 0.32:
        return False
    # nunca mascarar virilha / pernas
    if box.y > int(height * 0.78):
        return False
    return True


def _dedupe_boxes(boxes: Sequence[Box]) -> list[Box]:
    from quem_e_este_leao.validation import merge_boxes

    return merge_boxes(boxes)


def try_ocr_boxes(image_bgr: np.ndarray, player=None, faces: Sequence[Box] | None = None) -> list[Box]:
    """OCR opcional: só nome/alcunha e número da camisola do jogador.

    Não devolve patches de evento, patrocínio ou publicidade.
    """
    try:
        from quem_e_este_leao.validation import identifying_boxes, tesseract_available
    except Exception:
        return []
    if not tesseract_available():
        return []
    try:
        h, w = image_bgr.shape[:2]
        boxes = list(identifying_boxes(image_bgr, player))
        for face in faces or ():
            roi = _torso_roi(face, w, h)
            ys, xs = roi.as_slice()
            crop = image_bgr[ys, xs]
            if crop.size < 80:
                continue
            for b in identifying_boxes(crop, player):
                boxes.append(Box(roi.x + b.x, roi.y + b.y, b.w, b.h).clip(w, h))
        return [b for b in boxes if _sane_extra_box(b, w, h)]
    except Exception:
        log.info("OCR indisponível — a usar a heurística do número.")
        return []


def pixelate(img: np.ndarray, box: Box, block: int) -> None:
    ys, xs = box.as_slice()
    roi = img[ys, xs]
    if roi.size == 0:
        return
    h, w = roi.shape[:2]
    bw = max(1, w // max(4, block))
    bh = max(1, h // max(4, block))
    small = cv2.resize(roi, (bw, bh), interpolation=cv2.INTER_LINEAR)
    pix = cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)
    img[ys, xs] = pix


def gaussian_blur(img: np.ndarray, box: Box, ksize: int) -> None:
    k = ksize if ksize % 2 == 1 else ksize + 1
    k = max(3, k)
    ys, xs = box.as_slice()
    roi = img[ys, xs]
    if roi.size == 0:
        return
    img[ys, xs] = cv2.GaussianBlur(roi, (k, k), 0)


def _feathered_ellipse_mask(h: int, w: int) -> np.ndarray:
    """Núcleo opaco (máscara=1) com pluma só no bordo — cara irreconhecível, sem rectângulo preto."""
    mask = np.zeros((h, w), dtype=np.float32)
    cx, cy = int(w / 2.0), int(h / 2.0)
    axes = (max(1, int(w * 0.48)), max(1, int(h * 0.48)))
    cv2.ellipse(mask, (cx, cy), axes, 0, 0, 360, 1.0, -1)
    k = max(7, (min(h, w) // 16) | 1)
    mask = cv2.GaussianBlur(mask, (k, k), 0)
    # O núcleo fica a 1.0; só a coroa exterior mistura com o original.
    mask = np.clip(mask * 1.35, 0.0, 1.0)
    return mask


def _feathered_roundrect_mask(h: int, w: int) -> np.ndarray:
    mask = np.zeros((h, w), dtype=np.float32)
    radius = max(4, min(h, w) // 6)
    cv2.rectangle(mask, (2, 2), (w - 3, h - 3), 1.0, -1)
    k = max(5, (min(h, w) // 8) | 1)
    mask = cv2.GaussianBlur(mask, (k, k), 0)
    # keep corners from being a hard box: already blurred
    _ = radius
    peak = float(mask.max()) or 1.0
    return mask / peak


def mask_region(
    img: np.ndarray,
    box: Box,
    *,
    pixel_block: int,
    blur_ksize: int,
    shape: str = "ellipse",
    extra_blur: int = 0,
) -> None:
    """Pixelize + blur só dentro de uma máscara com pluma — não um rectângulo preto."""
    h_img, w_img = img.shape[:2]
    box = box.clip(w_img, h_img)
    ys, xs = box.as_slice()
    roi = img[ys, xs]
    if roi.size == 0:
        return
    h, w = roi.shape[:2]
    anonymized = roi.copy()
    # pixelate full ROI then blur, then blend with ellipse/round-rect
    bw = max(1, w // max(4, pixel_block))
    bh = max(1, h // max(4, pixel_block))
    small = cv2.resize(anonymized, (bw, bh), interpolation=cv2.INTER_LINEAR)
    anonymized = cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)
    k = blur_ksize if blur_ksize % 2 == 1 else blur_ksize + 1
    k = max(3, k)
    anonymized = cv2.GaussianBlur(anonymized, (k, k), 0)
    if extra_blur:
        k2 = extra_blur if extra_blur % 2 == 1 else extra_blur + 1
        anonymized = cv2.GaussianBlur(anonymized, (max(3, k2), max(3, k2)), 0)
    if shape == "ellipse":
        mask = _feathered_ellipse_mask(h, w)
    else:
        mask = _feathered_roundrect_mask(h, w)
    mask3 = mask[:, :, None]
    blended = anonymized.astype(np.float32) * mask3 + roi.astype(np.float32) * (1.0 - mask3)
    img[ys, xs] = blended.astype(np.uint8)


def sharpness(img: np.ndarray, boxes: Iterable[Box]) -> float:
    values: list[float] = []
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    for box in boxes:
        ys, xs = box.as_slice()
        roi = gray[ys, xs]
        if roi.size < 16:
            continue
        values.append(float(cv2.Laplacian(roi, cv2.CV_64F).var()))
    return float(np.mean(values)) if values else 0.0


def anonymize(
    image_bgr: np.ndarray,
    difficulty: Difficulty,
    *,
    forced_faces: list[Box] | None = None,
    abort_if_recognizable: bool = True,
    allow_geometry_fallback: bool = False,
    player=None,
    ocr_enabled: bool = True,
) -> AnonymizeResult:
    params = PARAMS[difficulty]
    h, w = image_bgr.shape[:2]
    work = image_bgr.copy()
    used_fallback = False
    extra: list[Box] = []
    detected: list[DetectedFace] = []

    if forced_faces is not None:
        faces = list(forced_faces)
    else:
        detected = detect_faces_scored(work, try_rotations=True)
        faces = [f.box for f in detected]
        if not faces:
            if allow_geometry_fallback:
                face, chest = geometry_fallback(h, w)
                faces = [face]
                extra.append(chest)
                used_fallback = True
                log.info("Detector de cara falhou — fallback geométrico (apenas modo explícito).")
            else:
                raise AnonymizationError(
                    "Cara não detectada de forma fiável — a rejeitar a fotografia."
                )

    core_faces = list(faces)
    # expand + padding da caixa ORIGINAL (cabelo / queixo), sem tapar o corpo inteiro
    faces = [
        f.pad(params.pad_x, params.pad_y, w, h).expand(params.face_expand, w, h)
        for f in faces
    ]

    if params.hide_name_number:
        # Só nome/número do jogador. Patches de evento / publicidade ficam.
        if ocr_enabled:
            extra.extend(try_ocr_boxes(work, player, core_faces))
        extra.extend(detect_number_like_boxes(work, core_faces))
        extra = [b for b in _dedupe_boxes(extra) if _sane_extra_box(b, w, h)]
        if not extra and not torso_has_wide_banner(work, core_faces):
            extra.extend(number_from_face(f, w, h) for f in core_faces)
            extra = [b for b in extra if _sane_extra_box(b, w, h)]

    # HARD: só caixas de nome/número. NÃO tapar o terço inferior
    # (era isto que pixelizava calções / virilha). NÃO tapar banners de evento.

    before = sharpness(work, core_faces)

    extra_blur = params.blur_ksize + 24 if difficulty is Difficulty.HARD else 0
    for face in faces:
        mask_region(
            work,
            face,
            pixel_block=params.pixel_block,
            blur_ksize=params.blur_ksize,
            shape="ellipse",
            extra_blur=extra_blur,
        )

    if params.hide_name_number:
        for box in extra:
            mask_region(
                work,
                box,
                pixel_block=max(8, params.pixel_block // 2),
                blur_ksize=max(31, params.blur_ksize - 10),
                shape="roundrect",
            )

    after = sharpness(work, core_faces)
    ratio = (after / before) if before > 1e-6 else 0.0
    log.info(
        "Anonimização %s: fallback=%s sharpness_ratio=%.3f faces=%s",
        difficulty.value,
        used_fallback,
        ratio,
        len(faces),
    )
    if (
        abort_if_recognizable
        and difficulty is not Difficulty.EASY
        and before > 30
        and ratio > params.min_sharpness_ratio
    ):
        raise AnonymizationError(
            f"A cara continua demasiado nítida (ratio={ratio:.2f}) — a abortar candidato."
        )
    return AnonymizeResult(
        image_bgr=work,
        face_boxes=faces,
        extra_boxes=extra,
        used_fallback=used_fallback,
        face_sharpness_before=before,
        face_sharpness_after=after,
        detected=detected,
    )


def _contain_resize(img: Image.Image, tw: int, th: int, fill: tuple[int, int, int]) -> Image.Image:
    """Escala uniformemente para caber (sem distorcer nem cortar)."""
    scale = min(tw / img.width, th / img.height)
    nw, nh = max(1, int(img.width * scale)), max(1, int(img.height * scale))
    resized = img.resize((nw, nh), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (tw, th), fill)
    canvas.paste(resized, ((tw - nw) // 2, (th - nh) // 2))
    return canvas


def _cover_on_face(
    img: Image.Image, tw: int, th: int, face: Box | None, src_w: int, src_h: int
) -> Image.Image:
    """Cover sem distorcer; centra na cara se conhecida."""
    scale = max(tw / img.width, th / img.height)
    nw, nh = int(img.width * scale), int(img.height * scale)
    resized = img.resize((nw, nh), Image.Resampling.LANCZOS)
    if face is not None and src_w > 0 and src_h > 0:
        cx = (face.x + face.w / 2) / src_w * nw
        cy = (face.y + face.h / 2) / src_h * nh
        left = int(cx - tw / 2)
        top = int(cy - th / 2)
    else:
        left = (nw - tw) // 2
        top = (nh - th) // 2
    left = max(0, min(left, nw - tw))
    top = max(0, min(top, nh - th))
    return resized.crop((left, top, left + tw, top + th))


def _draw_lion_badge(draw: ImageDraw.ImageDraw, cx: int, cy: int, r: int) -> None:
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=WHITE, outline=GOLD, width=3)
    draw.ellipse((cx - r + 6, cy - r + 6, cx + r - 6, cy + r - 6), fill=SPORTING_GREEN)
    for ang, _rad in ((-40, r - 2), (0, r), (40, r - 2), (180, r - 4)):
        x = cx + int(math.cos(math.radians(ang)) * (r + 2))
        y = cy + int(math.sin(math.radians(ang)) * (r + 2))
        draw.ellipse((x - 7, y - 7, x + 7, y + 7), fill=GOLD)
    draw.text((cx - 10, cy - 11), "S", font=_font(FONT_BOLD, 22), fill=WHITE)


def compose_frame(
    image_bgr: np.ndarray,
    *,
    desafio_n: int | None = None,
    face_boxes: Sequence[Box] | None = None,
    fit: str = "contain",
) -> Image.Image:
    """Moldura 1080×1080: branding no topo, foto ao centro, título em baixo.

    A fotografia nunca é esticada (aspect ratio preservado).
    """
    rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    photo = Image.fromarray(rgb)
    src_h, src_w = image_bgr.shape[:2]
    canvas = Image.new("RGB", (CANVAS, CANVAS), DARK_GREEN)
    draw = ImageDraw.Draw(canvas)

    # cabeçalho — só branding
    draw.rectangle((0, 0, CANVAS, HEADER_H), fill=SPORTING_GREEN)
    draw.rectangle((0, HEADER_H - 3, CANVAS, HEADER_H), fill=WHITE)
    _draw_lion_badge(draw, 48, HEADER_H // 2, 22)
    brand_font = _font(FONT_BOLD, 28)
    draw.text((84, 22), "#SpacesSporting", font=brand_font, fill=WHITE)

    photo_top = HEADER_H + GAP
    photo_bottom = CANVAS - FOOTER_H - GAP
    photo_left = SIDE
    photo_right = CANVAS - SIDE
    pw, ph = photo_right - photo_left, photo_bottom - photo_top
    face = face_boxes[0] if face_boxes else None
    if fit == "cover":
        hero = _cover_on_face(photo, pw, ph, face, src_w, src_h)
    else:
        hero = _contain_resize(photo, pw, ph, DARK_GREEN)

    vignette = Image.new("L", hero.size, 0)
    vdraw = ImageDraw.Draw(vignette)
    vdraw.rounded_rectangle((0, 0, pw - 1, ph - 1), radius=22, fill=255)
    vignette = vignette.filter(ImageFilter.GaussianBlur(5))
    rounded = Image.new("RGB", hero.size, DARK_GREEN)
    rounded.paste(hero, (0, 0))
    canvas.paste(rounded, (photo_left, photo_top), vignette)

    draw.rounded_rectangle(
        (photo_left - 2, photo_top - 2, photo_right + 1, photo_bottom + 1),
        radius=24,
        outline=WHITE,
        width=2,
    )

    fy = CANVAS - FOOTER_H
    draw.rectangle((0, fy, CANVAS, CANVAS), fill=SPORTING_GREEN)
    draw.rectangle((0, fy, CANVAS, fy + 3), fill=WHITE)
    title_font = _font(FONT_BOLD, 44)
    title = "QUEM É ESTE LEÃO?"
    # centrar o título
    bbox = draw.textbbox((0, 0), title, font=title_font)
    tw = bbox[2] - bbox[0]
    draw.text(((CANVAS - tw) // 2, fy + 28), title, font=title_font, fill=WHITE)

    small = _font(FONT_REG, 22)
    if desafio_n is not None:
        label = f"desafio nº {desafio_n}"
        lb = draw.textbbox((0, 0), label, font=small)
        lw = lb[2] - lb[0]
        draw.text(((CANVAS - lw) // 2, fy + 90), label, font=small, fill=OFF_WHITE)
    else:
        draw.text((SIDE, fy + 100), "SCP", font=small, fill=WHITE)

    gy = fy + 102
    draw.ellipse((CANVAS - 118, gy, CANVAS - 90, gy + 28), fill=WHITE, outline=WHITE)
    draw.ellipse((CANVAS - 114, gy + 4, CANVAS - 94, gy + 24), fill=SPORTING_GREEN)
    draw.ellipse((CANVAS - 80, gy, CANVAS - 52, gy + 28), fill=WHITE, outline=WHITE)
    return canvas


def strip_exif_save(image: Image.Image, dest: Path, quality: int = 92) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    clean = Image.new(image.mode, image.size)
    clean.putdata(list(image.getdata()))
    clean.save(dest, format="JPEG", quality=quality, optimize=True, exif=b"")
    return dest


def opaque_filename(quiz_id: str) -> str:
    hex_part = quiz_id.replace("-", "")[:16]
    return f"quiz_{hex_part}.jpg"


def process_to_post(
    source: Path,
    dest: Path,
    difficulty: Difficulty,
    *,
    abort_if_recognizable: bool = True,
    forced_faces: list[Box] | None = None,
    player=None,
    desafio_n: int | None = None,
    second_pass: bool = True,
    ocr_enabled: bool = True,
    allow_geometry_fallback: bool = False,
) -> AnonymizeResult:
    data = np.fromfile(str(source), dtype=np.uint8)
    image_bgr = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image_bgr is None:
        raise RuntimeError(f"Não foi possível ler a fotografia: {source}")
    result = anonymize(
        image_bgr,
        difficulty,
        forced_faces=forced_faces,
        abort_if_recognizable=abort_if_recognizable,
        allow_geometry_fallback=allow_geometry_fallback,
        player=player,
        ocr_enabled=ocr_enabled,
    )
    if second_pass:
        from quem_e_este_leao.validation import validate_anonymized

        report = validate_anonymized(
            result.image_bgr,
            masked_boxes=result.face_boxes + result.extra_boxes,
            player=player,
            ocr_enabled=ocr_enabled,
            abort_if_recognizable=abort_if_recognizable,
        )
        if abort_if_recognizable and not report.ok:
            raise AnonymizationError(f"Segunda passagem falhou: {report.reason}")
    frame = compose_frame(
        result.image_bgr,
        desafio_n=desafio_n,
        face_boxes=result.face_boxes,
        fit="contain",
    )
    strip_exif_save(frame, dest)
    log.info("Quadro composto gravado (%s).", dest.name)
    return result
