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
from quem_e_este_leao.logging_setup import get_logger

log = get_logger("processing")

CANVAS = 1080
SPORTING_GREEN = (0, 128, 87)
DARK_GREEN = (8, 42, 30)
WHITE = (255, 255, 255)
OFF_WHITE = (246, 248, 246)
GOLD = (201, 168, 76)

FONT_BOLD = Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf")
FONT_REG = Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf")
FONT_FALLBACK = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")

HEADER_H = 96
FOOTER_H = 80
SIDE = 40
GAP = 18


class AnonymizationError(RuntimeError):
    """A fotografia continua reconhecível — abortar o candidato."""


@dataclass(frozen=True)
class Box:
    x: int
    y: int
    w: int
    h: int

    def clip(self, width: int, height: int) -> "Box":
        x = max(0, self.x)
        y = max(0, self.y)
        w = max(1, min(self.w, width - x))
        h = max(1, min(self.h, height - y))
        return Box(x, y, w, h)

    def expand(self, factor: float, width: int, height: int) -> "Box":
        cx, cy = self.x + self.w / 2, self.y + self.h / 2
        nw, nh = self.w * factor, self.h * factor
        return Box(int(cx - nw / 2), int(cy - nh / 2), int(nw), int(nh)).clip(width, height)

    def as_slice(self) -> tuple[slice, slice]:
        return slice(self.y, self.y + self.h), slice(self.x, self.x + self.w)

    @property
    def area(self) -> int:
        return self.w * self.h


@dataclass
class DifficultyParams:
    pixel_block: int
    blur_ksize: int
    face_expand: float
    hide_name_number: bool
    hide_extra: bool
    min_sharpness_ratio: float


PARAMS: dict[Difficulty, DifficultyParams] = {
    Difficulty.EASY: DifficultyParams(12, 31, 1.15, False, False, 0.55),
    Difficulty.MEDIUM: DifficultyParams(22, 61, 1.35, True, False, 0.28),
    Difficulty.HARD: DifficultyParams(36, 91, 1.55, True, True, 0.16),
}


@dataclass
class AnonymizeResult:
    image_bgr: np.ndarray
    face_boxes: list[Box]
    extra_boxes: list[Box]
    used_fallback: bool
    face_sharpness_before: float
    face_sharpness_after: float


def _font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    for candidate in (path, FONT_BOLD, FONT_FALLBACK):
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def _haar_cascade(name: str) -> cv2.CascadeClassifier | None:
    base = getattr(cv2, "data", None)
    if base is None:
        return None
    path = Path(base.haarcascades) / name
    if not path.exists():
        return None
    clf = cv2.CascadeClassifier(str(path))
    return clf if not clf.empty() else None


def detect_faces(gray: np.ndarray) -> list[Box]:
    boxes: list[Box] = []
    h_img, w_img = gray.shape[:2]
    min_side = max(32, int(min(h_img, w_img) * 0.06))
    for name, scale, neigh in (
        ("haarcascade_frontalface_default.xml", 1.1, 5),
        ("haarcascade_frontalface_alt2.xml", 1.1, 5),
        ("haarcascade_profileface.xml", 1.12, 6),
    ):
        clf = _haar_cascade(name)
        if clf is None:
            continue
        found = clf.detectMultiScale(gray, scaleFactor=scale, minNeighbors=neigh, minSize=(min_side, min_side))
        for x, y, w, h in found:
            boxes.append(Box(int(x), int(y), int(w), int(h)))
    kept: list[Box] = []
    for b in _nms(boxes, iou_thresh=0.35):
        cy = b.y + b.h / 2
        # falsos positivos típicos: calções, relvado, braços — a cara está no terço superior
        if cy > h_img * 0.58:
            continue
        if b.w < min_side or b.h < min_side:
            continue
        kept.append(b)
    if not kept:
        return []
    kept.sort(key=lambda b: b.area, reverse=True)
    return kept[:2]


def _iou(a: Box, b: Box) -> float:
    x1, y1 = max(a.x, b.x), max(a.y, b.y)
    x2, y2 = min(a.x + a.w, b.x + b.w), min(a.y + a.h, b.y + b.h)
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    union = a.area + b.area - inter
    return inter / union if union else 0.0


def _nms(boxes: Sequence[Box], iou_thresh: float) -> list[Box]:
    ordered = sorted(boxes, key=lambda b: b.area, reverse=True)
    keep: list[Box] = []
    for b in ordered:
        if all(_iou(b, k) < iou_thresh for k in keep):
            keep.append(b)
    return keep


def geometry_fallback(height: int, width: int) -> tuple[Box, Box]:
    """Banda superior (~35%) para a cara e zona de peito para o número."""
    face = Box(int(width * 0.18), int(height * 0.02), int(width * 0.64), int(height * 0.35))
    chest = Box(int(width * 0.28), int(height * 0.38), int(width * 0.44), int(height * 0.28))
    return face.clip(width, height), chest.clip(width, height)


def chest_from_face(face: Box, width: int, height: int) -> Box:
    """Zona do número no peito, logo abaixo da cara — sem tapar o resto da camisola."""
    y = face.y + face.h + int(face.h * 0.08)
    h = max(int(face.h * 0.85), 28)
    x = face.x + int(face.w * 0.12)
    w = max(int(face.w * 0.76), 28)
    return Box(x, y, w, h).clip(width, height)


def try_ocr_boxes(image_bgr: np.ndarray) -> list[Box]:
    """OCR opcional (pytesseract). Falha de forma graciosa se o tesseract não existir."""
    try:
        import pytesseract
        from pytesseract import Output
    except Exception:
        return []
    try:
        rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
        data = pytesseract.image_to_data(rgb, output_type=Output.DICT, config="--psm 11")
    except Exception:
        log.info("OCR indisponível — a usar fallback geométrico para texto/número.")
        return []
    boxes: list[Box] = []
    n = len(data.get("text", []))
    for i in range(n):
        text = (data["text"][i] or "").strip()
        if not text:
            continue
        try:
            conf = float(data.get("conf", [-1])[i])
        except (IndexError, TypeError, ValueError):
            conf = -1.0
        if conf >= 0 and conf < 40:
            continue
        # números de camisola ou palavras com aspecto de nome
        if text.isdigit() or (len(text) >= 3 and text.replace("-", "").isalpha() and text.isupper()):
            boxes.append(
                Box(int(data["left"][i]), int(data["top"][i]), int(data["width"][i]), int(data["height"][i]))
            )
    return boxes


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
) -> AnonymizeResult:
    params = PARAMS[difficulty]
    h, w = image_bgr.shape[:2]
    work = image_bgr.copy()
    gray = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY)
    faces = list(forced_faces) if forced_faces is not None else detect_faces(gray)
    used_fallback = False
    extra: list[Box] = []

    if not faces:
        face, chest = geometry_fallback(h, w)
        faces = [face]
        extra.append(chest)
        used_fallback = True
        log.info("Detector de cara falhou — fallback da banda superior + peito.")
    else:
        faces = [f.expand(params.face_expand, w, h) for f in faces]
        if params.hide_name_number:
            extra.extend(chest_from_face(f, w, h) for f in faces)

    if params.hide_name_number:
        extra.extend(try_ocr_boxes(work))

    if params.hide_extra:
        # zona de faixa de nomes no terço inferior (faixas publicitárias / costas)
        extra.append(Box(int(w * 0.1), int(h * 0.72), int(w * 0.8), int(h * 0.18)).clip(w, h))

    before = sharpness(work, faces)

    for face in faces:
        pixelate(work, face, params.pixel_block)
        gaussian_blur(work, face, params.blur_ksize)
        if difficulty is Difficulty.HARD:
            gaussian_blur(work, face, params.blur_ksize + 20)

    if params.hide_name_number:
        for box in extra:
            gaussian_blur(work, box, max(31, params.blur_ksize - 10))
            pixelate(work, box, max(8, params.pixel_block // 2))

    after = sharpness(work, faces)
    ratio = (after / before) if before > 1e-6 else 0.0
    log.info(
        "Anonimização %s: fallback=%s sharpness_ratio=%.3f",
        difficulty.value,
        used_fallback,
        ratio,
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
    )


def _cover_resize(img: Image.Image, tw: int, th: int) -> Image.Image:
    scale = max(tw / img.width, th / img.height)
    nw, nh = int(img.width * scale), int(img.height * scale)
    resized = img.resize((nw, nh), Image.Resampling.LANCZOS)
    left = (nw - tw) // 2
    top = (nh - th) // 2
    return resized.crop((left, top, left + tw, top + th))


def _draw_lion_badge(draw: ImageDraw.ImageDraw, cx: int, cy: int, r: int) -> None:
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=WHITE, outline=GOLD, width=3)
    draw.ellipse((cx - r + 6, cy - r + 6, cx + r - 6, cy + r - 6), fill=SPORTING_GREEN)
    # juba simplificada (não é o emblema oficial)
    for ang, rad in ((-40, r - 2), (0, r), (40, r - 2), (180, r - 4)):
        x = cx + int(math.cos(math.radians(ang)) * (r + 2))
        y = cy + int(math.sin(math.radians(ang)) * (r + 2))
        draw.ellipse((x - 7, y - 7, x + 7, y + 7), fill=GOLD)
    draw.text((cx - 10, cy - 11), "S", font=_font(FONT_BOLD, 22), fill=WHITE)


def compose_frame(image_bgr: np.ndarray) -> Image.Image:
    """Moldura 1080×1080: foto como herói, barra #SpacesSporting, sem tapar o jogador."""
    rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    photo = Image.fromarray(rgb)
    canvas = Image.new("RGB", (CANVAS, CANVAS), DARK_GREEN)
    draw = ImageDraw.Draw(canvas)

    # cabeçalho
    draw.rectangle((0, 0, CANVAS, HEADER_H), fill=SPORTING_GREEN)
    draw.rectangle((0, HEADER_H - 4, CANVAS, HEADER_H), fill=WHITE)
    _draw_lion_badge(draw, 56, HEADER_H // 2, 28)
    title_font = _font(FONT_BOLD, 42)
    draw.text((100, 26), "QUEM É ESTE LEÃO?", font=title_font, fill=WHITE)

    # área da fotografia
    photo_top = HEADER_H + GAP
    photo_bottom = CANVAS - FOOTER_H - GAP
    photo_left = SIDE
    photo_right = CANVAS - SIDE
    pw, ph = photo_right - photo_left, photo_bottom - photo_top
    hero = _cover_resize(photo, pw, ph)
    # ligeira vinheta nas bordas, sem tapar o centro
    vignette = Image.new("L", hero.size, 0)
    vdraw = ImageDraw.Draw(vignette)
    vdraw.rounded_rectangle((0, 0, pw - 1, ph - 1), radius=18, fill=255)
    vignette = vignette.filter(ImageFilter.GaussianBlur(6))
    rounded = Image.new("RGB", hero.size, DARK_GREEN)
    rounded.paste(hero, (0, 0))
    mask = vignette
    canvas.paste(rounded, (photo_left, photo_top), mask)

    # filete branco fino
    draw.rounded_rectangle(
        (photo_left - 2, photo_top - 2, photo_right + 1, photo_bottom + 1),
        radius=20,
        outline=WHITE,
        width=2,
    )

    # rodapé
    fy = CANVAS - FOOTER_H
    draw.rectangle((0, fy, CANVAS, CANVAS), fill=SPORTING_GREEN)
    draw.rectangle((0, fy, CANVAS, fy + 4), fill=WHITE)
    foot = _font(FONT_BOLD, 28)
    draw.text((SIDE, fy + 24), "#SpacesSporting", font=foot, fill=WHITE)
    small = _font(FONT_REG, 22)
    draw.text((CANVAS - 250, fy + 28), "SCP", font=small, fill=WHITE)
    # círculos verde e branco (as fontes do sistema não têm emoji)
    gy = fy + 32
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
    # quiz_id já é hex opaco
    hex_part = quiz_id.replace("-", "")[:16]
    return f"quiz_{hex_part}.jpg"


def process_to_post(
    source: Path,
    dest: Path,
    difficulty: Difficulty,
    *,
    abort_if_recognizable: bool = True,
    forced_faces: list[Box] | None = None,
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
    )
    frame = compose_frame(result.image_bgr)
    strip_exif_save(frame, dest)
    log.info("Quadro composto gravado (%s).", dest.name)
    return result
