"""Esqueleto: «Quem É Esta Lenda?» — ênfase em jogadores históricos."""

from __future__ import annotations

from quem_e_este_leao.config import Difficulty
from quem_e_este_leao.formats.base import QuizCopy, QuizFormat, register
from quem_e_este_leao.players import Player


class QuemEEstaLendaFormat(QuizFormat):
    id = "quem_e_esta_lenda"
    display_name = "Quem É Esta Lenda?"
    implemented = False

    def build_copy(self, player: Player, clue: str, difficulty: Difficulty) -> QuizCopy:
        raise NotImplementedError(
            "«Quem É Esta Lenda?» ainda não está publicado. "
            "Usar o formato quem_e_este_leao. Ver README, secção Formatos."
        )


register(QuemEEstaLendaFormat())
