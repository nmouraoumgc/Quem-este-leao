"""Detecção de caras: YuNet (OpenCV DNN) com Haar como fallback.

Se nenhum detector encontrar uma cara de forma fiável, a fotografia deve ser
REJEITADA — nunca se publica com um desfoque geométrico «à sorte».
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import cv2
import numpy as np

from quem_e_este_leao.logging_setup import get_logger

log = get_logger("detection")

DEFAULT_YUNET = Path(__file__).resolve().parents[2] / "assets" / "models" / "face_detection_yunet_2023mar.onnx"

# Limiar YuNet: preferir falsos negativos a caras dúbias.
YUNET_SCORE = 0.55
YUNET_NMS = 0.3
YUNET_TOP_K = 5000


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

    def pad(self, px: float, py: float, width: int, height: int) -> "Box":
        """Expande em fracção da própria caixa (cabelo / queixo)."""
        dx, dy = int(self.w * px), int(self.h * py)
        return Box(self.x - dx, self.y - dy, self.w + 2 * dx, self.h + 2 * dy).clip(width, height)

    def as_slice(self) -> tuple[slice, slice]:
        return slice(self.y, self.y + self.h), slice(self.x, self.x + self.w)

    @property
    def area(self) -> int:
        return self.w * self.h

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2


@dataclass(frozen=True)
class DetectedFace:
    box: Box
    score: float
    source: str  # yunet | haar | rotated-yunet


def iou(a: Box, b: Box) -> float:
    x1, y1 = max(a.x, b.x), max(a.y, b.y)
    x2, y2 = min(a.x + a.w, b.x + b.w), min(a.y + a.h, b.y + b.h)
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    union = a.area + b.area - inter
    return inter / union if union else 0.0


def nms(faces: Sequence[DetectedFace], iou_thresh: float = 0.35) -> list[DetectedFace]:
    ordered = sorted(faces, key=lambda f: (f.score, f.box.area), reverse=True)
    keep: list[DetectedFace] = []
    for f in ordered:
        if all(iou(f.box, k.box) < iou_thresh for k in keep):
            keep.append(f)
    return keep


def _to_bgr(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    if image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
    return image


def _to_gray(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return image
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


_YUNET: cv2.FaceDetectorYN | None = None
_YUNET_PATH: str | None = None
_YUNET_FAILED = False


def _yunet(model_path: Path | None) -> cv2.FaceDetectorYN | None:
    global _YUNET, _YUNET_PATH, _YUNET_FAILED
    path = Path(model_path) if model_path else DEFAULT_YUNET
    key = str(path)
    if _YUNET is not None and _YUNET_PATH == key:
        return _YUNET
    if _YUNET_FAILED and _YUNET_PATH == key:
        return None
    if not path.exists():
        log.warning("Modelo YuNet ausente em %s — a usar Haar.", path.name)
        _YUNET_FAILED = True
        _YUNET_PATH = key
        return None
    try:
        det = cv2.FaceDetectorYN.create(
            str(path),
            "",
            (320, 320),
            YUNET_SCORE,
            YUNET_NMS,
            YUNET_TOP_K,
        )
        _YUNET = det
        _YUNET_PATH = key
        _YUNET_FAILED = False
        log.info("Detector YuNet carregado (%s).", path.name)
        return det
    except Exception as exc:  # noqa: BLE001
        log.warning("YuNet falhou a carregar (%s) — Haar como fallback.", type(exc).__name__)
        _YUNET_FAILED = True
        _YUNET_PATH = key
        return None


def detect_yunet(
    image: np.ndarray,
    *,
    model_path: Path | None = None,
    score_threshold: float = YUNET_SCORE,
) -> list[DetectedFace]:
    det = _yunet(model_path)
    if det is None:
        return []
    bgr = _to_bgr(image)
    h, w = bgr.shape[:2]
    if h < 16 or w < 16:
        return []
    try:
        det.setInputSize((w, h))
        det.setScoreThreshold(float(score_threshold))
        _retval, faces = det.detect(bgr)
    except Exception as exc:  # noqa: BLE001
        log.warning("YuNet detect() falhou: %s", type(exc).__name__)
        return []
    if faces is None or len(faces) == 0:
        return []
    out: list[DetectedFace] = []
    for row in faces:
        x, y, fw, fh = (int(round(v)) for v in row[:4])
        score = float(row[-1])
        if score < score_threshold:
            continue
        box = Box(x, y, fw, fh).clip(w, h)
        if box.w < 12 or box.h < 12:
            continue
        out.append(DetectedFace(box=box, score=score, source="yunet"))
    return out


def _haar_cascade(name: str) -> cv2.CascadeClassifier | None:
    base = getattr(cv2, "data", None)
    if base is None:
        return None
    path = Path(base.haarcascades) / name
    if not path.exists():
        return None
    clf = cv2.CascadeClassifier(str(path))
    return clf if not clf.empty() else None


def detect_haar(image: np.ndarray) -> list[DetectedFace]:
    gray = _to_gray(image)
    h_img, w_img = gray.shape[:2]
    min_side = max(24, int(min(h_img, w_img) * 0.05))
    boxes: list[DetectedFace] = []
    for name, scale, neigh, source_tag in (
        ("haarcascade_frontalface_default.xml", 1.08, 5, "haar"),
        ("haarcascade_frontalface_alt2.xml", 1.1, 5, "haar"),
        ("haarcascade_profileface.xml", 1.12, 5, "haar"),
    ):
        clf = _haar_cascade(name)
        if clf is None:
            continue
        found = clf.detectMultiScale(
            gray, scaleFactor=scale, minNeighbors=neigh, minSize=(min_side, min_side)
        )
        for x, y, w, h in found:
            boxes.append(
                DetectedFace(box=Box(int(x), int(y), int(w), int(h)), score=0.45, source=source_tag)
            )
    return nms(boxes, 0.35)


def _rotate(image: np.ndarray, angle: float) -> tuple[np.ndarray, np.ndarray]:
    h, w = image.shape[:2]
    center = (w / 2.0, h / 2.0)
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    rotated = cv2.warpAffine(image, matrix, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    return rotated, matrix


def _box_from_rotated(box: Box, matrix: np.ndarray, width: int, height: int) -> Box:
    """Project a box detected on a rotated image back to the original frame."""
    corners = np.array(
        [
            [box.x, box.y],
            [box.x + box.w, box.y],
            [box.x + box.w, box.y + box.h],
            [box.x, box.y + box.h],
        ],
        dtype=np.float32,
    )
    # Inverse affine
    inv = cv2.invertAffineTransform(matrix)
    ones = np.ones((4, 1), dtype=np.float32)
    pts = np.hstack([corners, ones])
    mapped = (inv @ pts.T).T
    xs, ys = mapped[:, 0], mapped[:, 1]
    x, y = int(xs.min()), int(ys.min())
    w, h = int(max(1, xs.max() - xs.min())), int(max(1, ys.max() - ys.min()))
    return Box(x, y, w, h).clip(width, height)


def detect_faces_scored(
    image: np.ndarray,
    *,
    model_path: Path | None = None,
    score_threshold: float = YUNET_SCORE,
    try_rotations: bool = True,
) -> list[DetectedFace]:
    """YuNet primeiro; Haar a seguir; pequenas rotações se ainda vazio."""
    bgr = _to_bgr(image)
    h, w = bgr.shape[:2]
    found = detect_yunet(bgr, model_path=model_path, score_threshold=score_threshold)
    if found:
        return _filter_plausible(nms(found), h, w)

    haar = detect_haar(bgr)
    if haar:
        log.info("YuNet sem caras — Haar encontrou %s.", len(haar))
        return _filter_plausible(haar, h, w)

    if try_rotations:
        for angle in (15.0, -15.0, 30.0, -30.0):
            rotated, matrix = _rotate(bgr, angle)
            rotated_faces = detect_yunet(
                rotated, model_path=model_path, score_threshold=score_threshold
            )
            if not rotated_faces:
                rotated_faces = detect_haar(rotated)
            if rotated_faces:
                mapped = [
                    DetectedFace(
                        box=_box_from_rotated(f.box, matrix, w, h),
                        score=f.score,
                        source="rotated-yunet" if f.source.startswith("yunet") else "haar",
                    )
                    for f in rotated_faces
                ]
                log.info("Cara encontrada após rotação de %.0f°.", angle)
                return _filter_plausible(nms(mapped), h, w)

    return []


def _filter_plausible(faces: Iterable[DetectedFace], height: int, width: int) -> list[DetectedFace]:
    """Descarta detecções minúsculas ou claramente no terço inferior (calções, relvado)."""
    min_side = max(16, int(min(height, width) * 0.03))
    kept: list[DetectedFace] = []
    for f in faces:
        b = f.box
        if b.w < min_side or b.h < min_side:
            continue
        # Cara típica: não está colada ao fundo da fotografia
        if b.cy > height * 0.82 and b.area < (height * width) * 0.04:
            continue
        kept.append(f)
    kept.sort(key=lambda f: (f.score, f.box.area), reverse=True)
    return kept


def detect_faces(
    image: np.ndarray,
    *,
    model_path: Path | None = None,
    score_threshold: float = YUNET_SCORE,
    try_rotations: bool = True,
) -> list[Box]:
    return [
        f.box
        for f in detect_faces_scored(
            image,
            model_path=model_path,
            score_threshold=score_threshold,
            try_rotations=try_rotations,
        )
    ]


def dominant_face(faces: Sequence[DetectedFace]) -> DetectedFace | None:
    if not faces:
        return None
    return max(faces, key=lambda f: f.box.area)
