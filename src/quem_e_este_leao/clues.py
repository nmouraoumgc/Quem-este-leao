"""Pistas a partir de atributos — nunca identificam o jogador pelo nome."""

from __future__ import annotations

import random
import re
import unicodedata
from typing import Sequence

from quem_e_este_leao.config import Difficulty
from quem_e_este_leao.logging_setup import get_logger
from quem_e_este_leao.players import Player

log = get_logger("clues")

NATIONALITY_ADJECTIVE: dict[str, str] = {
    "Portugal": "português",
    "Suécia": "sueco",
    "Dinamarca": "dinamarquês",
    "Costa do Marfim": "marfinense",
    "Moçambique": "moçambicano",
    "Japão": "japonês",
    "Uruguai": "uruguaio",
    "Países Baixos": "neerlandês",
    "Argélia": "argelino",
    "Brasil": "brasileiro",
    "Espanha": "espanhol",
    "Bélgica": "belga",
}

POSITION_PHRASE: dict[str, str] = {
    "avançado": "É avançado.",
    "extremo": "É extremo.",
    "médio": "É médio.",
    "médio defensivo": "É médio defensivo.",
    "defesa central": "É defesa central.",
    "lateral": "É lateral.",
    "guarda-redes": "É guarda-redes.",
}


def _fold(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch)).casefold()


def contains_identity(text: str, player: Player) -> bool:
    folded = _fold(text)
    for token in player.identity_tokens:
        t = _fold(token)
        if len(t) < 3:
            continue
        if re.search(rf"(?<!\w){re.escape(t)}(?!\w)", folded):
            return True
    return False


def _article_for_years(years: str) -> str:
    return f"Jogou no Sporting em {years}."


def _number_clue(numbers: Sequence[int]) -> str | None:
    if not numbers:
        return None
    n = numbers[0]
    return f"Usa/usou o número {n}."


def _champion_clue(player: Player) -> str | None:
    for a in player.achievements:
        folded = _fold(a)
        if "campeao nacional" in folded:
            return "Foi campeão nacional pelo Sporting."
    return None


def _academy_clue(player: Player) -> str | None:
    if player.academy:
        return "Saiu da Academia de Alcochete."
    for a in player.achievements:
        if "academia" in _fold(a) or "alcochete" in _fold(a):
            return "Saiu da Academia de Alcochete."
    return None


def _selecao_clue(player: Player) -> str | None:
    if player.national_team:
        if player.nationality == "Portugal":
            return "Já representou a Seleção Nacional."
        adj = NATIONALITY_ADJECTIVE.get(player.nationality)
        if adj:
            return f"Já foi internacional {adj}."
        return "Já foi internacional pela sua seleção."
    return None


def _nationality_clue(player: Player) -> str | None:
    adj = NATIONALITY_ADJECTIVE.get(player.nationality)
    if not adj:
        return None
    return f"É {adj}."


def _position_clue(player: Player) -> str | None:
    return POSITION_PHRASE.get(player.position)


def _subtle_achievement(player: Player) -> str | None:
    """Pista mais vaga, sem números únicos nem alcunhas."""
    for a in player.achievements:
        folded = _fold(a)
        if contains_identity(a, player):
            continue
        if "taça de portugal" in folded or "taca de portugal" in folded:
            return "Já ganhou a Taça de Portugal pelo Sporting."
        if "bola de prata" in folded or "melhor marcador da liga" in folded:
            return "Já foi melhor marcador da Liga ao serviço do Sporting."
        if "bota de ouro" in folded:
            return "Já venceu a Bota de Ouro europeia."
        if "jogador do ano" in folded:
            return "Já foi eleito jogador do ano da Liga."
        if "guarda-redes do ano" in folded:
            return "Já foi eleito guarda-redes do ano da Liga."
        if "campeao da europa" in folded or "campeão da europa" in folded:
            return "Foi campeão da Europa com a Seleção."
        if "bola de ouro" in folded:
            continue  # demasiado identificador se combinado com o resto
    if "–" in player.years_at_sporting or "-" in player.years_at_sporting:
        start = re.split(r"[–,]", player.years_at_sporting)[0].strip()
        if start[:3].isdigit():
            decade = start[:3] + "0"
            return f"Esteve em Alvalade na década de {decade}."
    return "Vestiu de verde e branco em Alvalade."


def candidate_clues(player: Player) -> list[str]:
    clues: list[str] = []
    for builder in (
        _nationality_clue,
        _position_clue,
        _champion_clue,
        _selecao_clue,
        _academy_clue,
        lambda p: _number_clue(p.shirt_numbers),
        lambda p: _article_for_years(p.years_at_sporting),
        _subtle_achievement,
    ):
        clue = builder(player)
        if clue and not contains_identity(clue, player):
            clues.append(clue)
    # unique
    seen: set[str] = set()
    unique: list[str] = []
    for c in clues:
        if c not in seen:
            seen.add(c)
            unique.append(c)
    return unique


def generate_clue(
    player: Player,
    difficulty: Difficulty,
    rng: random.Random | None = None,
) -> str:
    rng = rng or random.Random()
    candidates = candidate_clues(player)
    if not candidates:
        fallback = "Vestiu de verde e branco em Alvalade."
        if contains_identity(fallback, player):
            raise RuntimeError("Não foi possível gerar uma pista segura.")
        return fallback

    easy_preferred = []
    medium_preferred = []
    hard_preferred = []
    for c in candidates:
        if c.startswith("É ") and c.endswith("."):
            # nationality or position — fácil
            easy_preferred.append(c)
        if c.startswith("Usa/usou o número"):
            easy_preferred.append(c)
        if "campeão nacional" in c or "Seleção Nacional" in c:
            medium_preferred.append(c)
        if "Academia" in c or "década" in c or "Taça" in c or "Alvalade" in c:
            hard_preferred.append(c)
        if "internacional" in c:
            medium_preferred.append(c)

    if difficulty is Difficulty.EASY:
        pool = easy_preferred or candidates
    elif difficulty is Difficulty.HARD:
        pool = hard_preferred or medium_preferred or candidates
    else:
        pool = medium_preferred or [c for c in candidates if c not in easy_preferred] or candidates

    # Garantir que a pista fácil junta contexto simples se a dificuldade é EASY
    if difficulty is Difficulty.EASY and _nationality_clue(player) and _position_clue(player):
        combo = f"{_nationality_clue(player)} {_position_clue(player)}"
        if not contains_identity(combo, player):
            # 50% das vezes a pista fácil é a combinação, senão uma só
            if rng.random() < 0.55:
                return combo.strip()

    chosen = rng.choice(pool)
    if contains_identity(chosen, player):
        safe = [c for c in candidates if not contains_identity(c, player)]
        chosen = rng.choice(safe) if safe else "Vestiu de verde e branco em Alvalade."
    log.info("Pista gerada (%s).", difficulty.value)
    return chosen
