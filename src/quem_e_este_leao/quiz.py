"""Orquestração: escolher jogador, várias fotos, pontuar, pista, gravar o quiz."""

from __future__ import annotations

import json
import random
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from quem_e_este_leao import db
from quem_e_este_leao.clues import contains_identity, generate_clue
from quem_e_este_leao.config import Difficulty, ImageKind, RevealDelay, Settings
from quem_e_este_leao.formats.base import get_format
from quem_e_este_leao.images import ImageCandidate, collect_candidates
from quem_e_este_leao.logging_setup import get_logger, log_answer
from quem_e_este_leao.players import Player, load_players
from quem_e_este_leao.processing import (
    AnonymizationError,
    opaque_filename,
    process_to_post,
)
from quem_e_este_leao.scoring import rank_candidates, score_image

log = get_logger("quiz")

MAX_PLAYER_ATTEMPTS = 10


@dataclass
class GeneratedQuiz:
    quiz_id: str
    player: Player
    clue: str
    caption: str
    reveal_caption: str
    interesting_fact: str | None
    processed_image: Path
    original_image: Path
    attribution: dict
    difficulty: Difficulty
    reveal_at: datetime
    status: str
    image_kind: str = ImageKind.REAL.value
    image_source: str = ""


def new_quiz_id() -> str:
    return secrets.token_hex(8)


def _assert_no_leaks(player: Player, caption: str, clue: str, filename: str) -> None:
    if contains_identity(caption, player):
        raise RuntimeError("A legenda pública contém a identidade do jogador.")
    if contains_identity(clue, player):
        raise RuntimeError("A pista contém a identidade do jogador.")
    if contains_identity(filename, player):
        raise RuntimeError("O nome do ficheiro contém a identidade do jogador.")


def _try_candidates(
    candidates: list[ImageCandidate],
    *,
    settings: Settings,
    difficulty: Difficulty,
    dest: Path,
    player: Player,
    desafio_n: int | None,
    allow_synthetic: bool = False,
) -> ImageCandidate:
    """Pontua, tenta o melhor, e se a 2.ª passagem falhar passa ao seguinte."""
    pairs = [(c.path, c) for c in candidates]
    ranked = rank_candidates(
        pairs,
        model_path=settings.yunet_model_path,
        min_score=settings.min_image_score,
        player=player,
    )
    # Sintético só entra se explicitamente permitido; mesmo ranqueado, em produção não.
    if not allow_synthetic:
        ranked = [(m, s) for m, s in ranked if not getattr(m, "is_synthetic", False)]

    last_error: Exception | None = None
    tried = 0
    for cand, score in ranked:
        tried += 1
        log.info(
            "A tentar candidato %s (score=%.1f, source=%s).",
            cand.path.name,
            score.total,
            cand.source,
        )
        try:
            process_to_post(
                cand.path,
                dest,
                difficulty,
                abort_if_recognizable=settings.abort_if_recognizable,
                player=player,
                desafio_n=desafio_n,
                second_pass=True,
                ocr_enabled=settings.ocr_enabled,
                allow_geometry_fallback=False,
            )
            return cand
        except AnonymizationError as exc:
            last_error = exc
            log.info("Candidato rejeitado após processamento: %s", type(exc).__name__)
            continue
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            log.warning("Falha a processar candidato: %s", type(exc).__name__)
            continue

    # Sem ranking aceite: se allow_synthetic, último recurso já veio em candidates.
    if not ranked:
        # Ainda assim tentar locais pontuados abaixo do mínimo? Não — fiabilidade > velocidade.
        reasons = []
        for c in candidates:
            sc = score_image(c.path, model_path=settings.yunet_model_path, player=player)
            reasons.extend(sc.reject_reasons)
        log.info("Nenhum candidato passou a pontuação (%s).", ",".join(sorted(set(reasons))) or "vazio")

    raise AnonymizationError(
        f"Nenhum candidato seguro após {tried or len(candidates)} fotografias."
    ) from last_error


def generate_quiz(
    settings: Settings,
    *,
    difficulty: Difficulty | None = None,
    reveal_delay: RevealDelay | None = None,
    output_dir: Path | None = None,
    player: Player | None = None,
    rng: random.Random | None = None,
    allow_synthetic: bool | None = None,
) -> GeneratedQuiz:
    difficulty = difficulty or settings.difficulty
    reveal_delay = reveal_delay or settings.reveal_delay
    output_dir = output_dir or settings.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    rng = rng or random.Random()
    use_synth = settings.allow_synthetic if allow_synthetic is None else allow_synthetic
    fmt = get_format(settings.format_id)
    if not fmt.implemented:
        raise RuntimeError(f"O formato {fmt.id} ainda não está implementado.")

    players = load_players(settings.players_yaml)
    tz = ZoneInfo(settings.timezone)
    now = datetime.now(tz)
    reveal_at = now + timedelta(
        seconds=settings.reveal_delay_seconds
        if reveal_delay is None
        else {
            RevealDelay.MIN_30: 1800,
            RevealDelay.HOUR_1: 3600,
            RevealDelay.HOUR_3: 10800,
        }[reveal_delay]
    )

    exclude: set[str] = set()
    last_error: Exception | None = None
    chosen: Player | None = player
    candidate: ImageCandidate | None = None
    quiz_id = new_quiz_id()
    processed_path: Path | None = None
    forced_player = player is not None

    with db.session(settings.database_path) as conn:
        desafio_n = db.count_quizzes(conn) + 1
        for attempt in range(1, MAX_PLAYER_ATTEMPTS + 1):
            try:
                if not forced_player:
                    chosen = db.select_player(conn, players, rng, exclude=exclude)
                else:
                    chosen = player
                assert chosen is not None
                work = settings.output_dir / "_sources" / quiz_id
                cands = collect_candidates(
                    chosen,
                    settings,
                    work,
                    allow_synthetic=use_synth,
                )
                if not cands:
                    raise AnonymizationError("Sem fotografias para este jogador.")
                dest_name = opaque_filename(quiz_id)
                dest = output_dir / dest_name
                candidate = _try_candidates(
                    cands,
                    settings=settings,
                    difficulty=difficulty,
                    dest=dest,
                    player=chosen,
                    desafio_n=desafio_n,
                    allow_synthetic=use_synth,
                )
                processed_path = dest
                break
            except AnonymizationError as exc:
                last_error = exc
                log.info(
                    "Jogador descartado (imagem insegura), tentativa %s.", attempt
                )
                if chosen is not None:
                    exclude.add(chosen.id)
                if forced_player:
                    raise
                player = None
                quiz_id = new_quiz_id()
                continue
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                log.warning("Falha na tentativa %s: %s", attempt, type(exc).__name__)
                if chosen is not None:
                    exclude.add(chosen.id)
                if forced_player:
                    raise
                player = None
                quiz_id = new_quiz_id()
                continue
        else:
            raise RuntimeError(
                f"Não foi possível gerar um quiz seguro após {MAX_PLAYER_ATTEMPTS} tentativas."
            ) from last_error

        assert chosen is not None and candidate is not None and processed_path is not None
        clue = generate_clue(chosen, difficulty, rng, pool=players)
        copy = fmt.build_copy(chosen, clue, difficulty)
        _assert_no_leaks(chosen, copy.caption, copy.clue, processed_path.name)

        db.insert_quiz(
            conn,
            quiz_id=quiz_id,
            format_id=fmt.id,
            player=chosen,
            original_image_path=str(candidate.path),
            processed_image_path=str(processed_path),
            clue=copy.clue,
            caption=copy.caption,
            reveal_caption=copy.reveal_caption,
            reveal_dt=reveal_at.isoformat(),
            status=db.STATUS_DRAFT,
            difficulty=difficulty.value,
            image_attribution=candidate.attribution_json(),
            interesting_fact=copy.interesting_fact,
            image_source=candidate.source,
            image_kind=candidate.image_kind,
        )
        log.info("Quiz %s gerado (rascunho, %s).", quiz_id, difficulty.value)
        log_answer("Resposta do quiz %s: %s", quiz_id, chosen.display_name)

    return GeneratedQuiz(
        quiz_id=quiz_id,
        player=chosen,
        clue=copy.clue,
        caption=copy.caption,
        reveal_caption=copy.reveal_caption,
        interesting_fact=copy.interesting_fact,
        processed_image=processed_path,
        original_image=candidate.path,
        attribution=json.loads(candidate.attribution_json()),
        difficulty=difficulty,
        reveal_at=reveal_at,
        status=db.STATUS_DRAFT,
        image_kind=candidate.image_kind,
        image_source=candidate.source,
    )
