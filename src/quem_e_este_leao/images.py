"""Aquisição de fotografias: locais, Wikimedia Commons (vários candidatos), sintético só em testes."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import numpy as np
from PIL import Image, ImageDraw

from quem_e_este_leao.config import PROJECT_ROOT, ImageKind, Settings
from quem_e_este_leao.logging_setup import get_logger, log_answer
from quem_e_este_leao.players import Player

log = get_logger("images")

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
THUMB_WIDTH = 1280


@dataclass
class ImageCandidate:
    path: Path
    source: str
    attribution: dict[str, Any] = field(default_factory=dict)
    is_synthetic: bool = False
    image_kind: str = ImageKind.REAL.value

    def attribution_json(self) -> str:
        payload = dict(self.attribution)
        payload.setdefault("source", self.source)
        payload.setdefault("image_kind", self.image_kind)
        return json.dumps(payload, ensure_ascii=False)


def resolve_local(path_str: str, *, settings: Settings) -> Path | None:
    path = Path(path_str)
    candidates = [
        path if path.is_absolute() else PROJECT_ROOT / path,
        settings.assets_dir / path.name,
        PROJECT_ROOT / "assets" / "samples" / path.name,
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def _headers(settings: Settings) -> dict[str, str]:
    return {"User-Agent": settings.http_user_agent, "Accept": "application/json"}


def _opaque_src_name(key: str) -> str:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
    return f"src_{digest}.jpg"


def fetch_wikimedia_file(
    filename: str,
    dest_dir: Path,
    settings: Settings,
    *,
    timeout: float = 30.0,
) -> ImageCandidate | None:
    """Descarrega uma miniatura oficial da Wikimedia Commons."""
    title = filename if filename.startswith("File:") else f"File:{filename}"
    dest_dir.mkdir(parents=True, exist_ok=True)
    params = {
        "action": "query",
        "titles": title,
        "prop": "imageinfo",
        "iiprop": "url|size|mime|extmetadata",
        "iiurlwidth": str(THUMB_WIDTH),
        "format": "json",
    }
    try:
        with httpx.Client(headers=_headers(settings), timeout=timeout, follow_redirects=True) as client:
            resp = client.get(COMMONS_API, params=params)
            resp.raise_for_status()
            payload = resp.json()
            pages = payload.get("query", {}).get("pages", {})
            page = next(iter(pages.values()), None)
            if not page or "imageinfo" not in page:
                log.info("Wikimedia: ficheiro sem imageinfo.")
                return None
            info = page["imageinfo"][0]
            thumb = info.get("thumburl") or info.get("url")
            if not thumb:
                return None
            meta = info.get("extmetadata") or {}
            artist = (meta.get("Artist") or {}).get("value") or ""
            license_name = (meta.get("LicenseShortName") or {}).get("value") or ""
            img_resp = client.get(
                thumb, headers={"User-Agent": settings.http_user_agent, "Accept": "image/*"}
            )
            img_resp.raise_for_status()
            dest = dest_dir / _opaque_src_name(filename)
            dest.write_bytes(img_resp.content)
            log.info("Fotografia Wikimedia guardada (%s bytes).", dest.stat().st_size)
            return ImageCandidate(
                path=dest,
                source="wikimedia",
                attribution={
                    "filename": filename,
                    "url": info.get("descriptionurl"),
                    "artist": artist,
                    "license": license_name,
                },
                image_kind=ImageKind.REAL.value,
            )
    except Exception as exc:  # noqa: BLE001 — falha de rede não deve derrubar o generate
        log.warning("Falha a obter Wikimedia (%s): %s", filename, type(exc).__name__)
        return None


def search_wikimedia_many(
    query: str,
    dest_dir: Path,
    settings: Settings,
    *,
    limit: int | None = None,
    timeout: float = 30.0,
) -> list[ImageCandidate]:
    limit = limit or settings.wikimedia_search_limit
    params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "srnamespace": "6",
        "srlimit": str(max(1, min(limit, 20))),
        "format": "json",
    }
    found: list[ImageCandidate] = []
    seen: set[str] = set()
    try:
        with httpx.Client(headers=_headers(settings), timeout=timeout, follow_redirects=True) as client:
            resp = client.get(COMMONS_API, params=params)
            resp.raise_for_status()
            hits = resp.json().get("query", {}).get("search", [])
        for hit in hits:
            if len(found) >= limit:
                break
            title = hit.get("title") or ""
            if not title.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                continue
            filename = title.removeprefix("File:")
            key = filename.casefold()
            if key in seen:
                continue
            seen.add(key)
            cand = fetch_wikimedia_file(filename, dest_dir, settings, timeout=timeout)
            if cand:
                found.append(cand)
    except Exception as exc:  # noqa: BLE001
        log.warning("Pesquisa Wikimedia falhou: %s", type(exc).__name__)
    return found


def search_wikimedia(
    query: str,
    dest_dir: Path,
    settings: Settings,
    *,
    timeout: float = 30.0,
) -> ImageCandidate | None:
    many = search_wikimedia_many(query, dest_dir, settings, limit=1, timeout=timeout)
    return many[0] if many else None


def generate_synthetic_kit_photo(dest: Path, seed: int = 7) -> ImageCandidate:
    """Silhueta de um jogador de verde e branco — APENAS testes / desenvolvimento."""
    rng = np.random.default_rng(seed)
    _ = rng
    w, h = 900, 1200
    img = Image.new("RGB", (w, h), (18, 92, 48))
    draw = ImageDraw.Draw(img)
    for y in range(0, h, 40):
        shade = 18 + (y % 80) // 8
        draw.rectangle((0, y, w, y + 20), fill=(shade, 90 + shade, 40))
    torso = (320, 430, 580, 820)
    draw.rounded_rectangle(torso, radius=30, fill=(0, 128, 87))
    draw.rectangle((320, 520, 580, 545), fill=(255, 255, 255))
    draw.rectangle((320, 700, 580, 718), fill=(255, 255, 255))
    draw.text((410, 560), "9", fill=(255, 255, 255))
    draw.rounded_rectangle((230, 450, 330, 700), radius=20, fill=(0, 128, 87))
    draw.rounded_rectangle((570, 450, 670, 700), radius=20, fill=(0, 128, 87))
    draw.rounded_rectangle((340, 810, 560, 980), radius=12, fill=(245, 245, 245))
    draw.rectangle((360, 975, 420, 1180), fill=(16, 70, 36))
    draw.rectangle((480, 975, 540, 1180), fill=(16, 70, 36))
    head = (380, 210, 520, 400)
    draw.ellipse(head, fill=(214, 167, 124))
    draw.ellipse((385, 190, 515, 280), fill=(40, 28, 18))
    draw.ellipse((415, 280, 440, 305), fill=(40, 40, 40))
    draw.ellipse((460, 280, 485, 305), fill=(40, 40, 40))
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, "JPEG", quality=90)
    log.info("Fotografia sintética gerada em %s (SYNTHETIC_TEST).", dest.name)
    return ImageCandidate(
        path=dest,
        source="synthetic",
        attribution={"license": "generated-for-tests", "note": "silhueta verde-e-branco"},
        is_synthetic=True,
        image_kind=ImageKind.SYNTHETIC_TEST.value,
    )


def collect_candidates(
    player: Player,
    settings: Settings,
    work_dir: Path,
    *,
    allow_synthetic: bool | None = None,
    allow_wikimedia: bool | None = None,
) -> list[ImageCandidate]:
    """Recolhe VÁRIOS candidatos: local + Wikimedia (ficheiro e pesquisa).

    Sintético só se `allow_synthetic` / QEEL_ALLOW_SYNTHETIC estiver activo.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    use_wiki = settings.wikimedia_enabled if allow_wikimedia is None else allow_wikimedia
    use_synth = settings.allow_synthetic if allow_synthetic is None else allow_synthetic
    out: list[ImageCandidate] = []
    seen_paths: set[str] = set()

    def _add(cand: ImageCandidate | None) -> None:
        if cand is None:
            return
        key = str(cand.path.resolve())
        if key in seen_paths:
            return
        seen_paths.add(key)
        out.append(cand)

    if player.local_image:
        local = resolve_local(player.local_image, settings=settings)
        if local is not None:
            log.info("Fotografia local curada disponível.")
            log_answer("Fotografia local de %s: %s", player.display_name, local.name)
            _add(
                ImageCandidate(
                    path=local,
                    source="local",
                    attribution={
                        "local_image": player.local_image,
                        "note": "Ver assets/samples/ATTRIBUTION.md",
                    },
                    image_kind=ImageKind.REAL.value,
                )
            )

    if use_wiki and player.wikimedia_filename:
        _add(fetch_wikimedia_file(player.wikimedia_filename, work_dir, settings))

    if use_wiki and player.image_search_query:
        for cand in search_wikimedia_many(
            player.image_search_query,
            work_dir,
            settings,
            limit=min(settings.wikimedia_search_limit, settings.max_image_candidates),
        ):
            _add(cand)

    if use_synth:
        dest = work_dir / "synthetic_kit.jpg"
        _add(generate_synthetic_kit_photo(dest, seed=abs(hash(player.id)) % 10_000))

    log.info("Candidatos de imagem recolhidos: %s", len(out))
    return out[: settings.max_image_candidates] if settings.max_image_candidates else out


def acquire_image(
    player: Player,
    settings: Settings,
    work_dir: Path,
    *,
    allow_synthetic: bool | None = None,
    allow_wikimedia: bool | None = None,
) -> ImageCandidate:
    """Compat: devolve o primeiro candidato recolhido (sem pontuar).

    O pipeline de produção usa `collect_candidates` + `rank_candidates`.
    """
    use_synth = settings.allow_synthetic if allow_synthetic is None else allow_synthetic
    cands = collect_candidates(
        player,
        settings,
        work_dir,
        allow_synthetic=use_synth,
        allow_wikimedia=allow_wikimedia,
    )
    if not cands:
        raise RuntimeError("Não foi possível obter uma fotografia reutilizável.")
    # Preferir não-sintético
    real = [c for c in cands if not c.is_synthetic]
    return real[0] if real else cands[0]
