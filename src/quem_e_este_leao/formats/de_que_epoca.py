"""Esqueleto: «De Que Época?» — identificar a época pela camisola / contexto."""

from __future__ import annotations

from quem_e_este_leao.config import Difficulty
from quem_e_este_leao.formats.base import QuizCopy, QuizFormat, register
from quem_e_este_leao.players import Player


class DeQueEpocaFormat(QuizFormat):
    id = "de_que_epoca"
    display_name = "De Que Época?"
    implemented = False

    def build_copy(self, player: Player, clue: str, difficulty: Difficulty) -> QuizCopy:
        raise NotImplementedError(
            "«De Que Época?» ainda não está publicado. "
            "A resposta seria uma época (ex.: 2001/02), não um jogador. Ver README."
        )


register(DeQueEpocaFormat())
