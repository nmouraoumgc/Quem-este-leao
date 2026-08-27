"""Esqueleto: «Quem É Este Treinador?»."""

from __future__ import annotations

from quem_e_este_leao.config import Difficulty
from quem_e_este_leao.formats.base import QuizCopy, QuizFormat, register
from quem_e_este_leao.players import Player


class QuemEEsteTreinadorFormat(QuizFormat):
    id = "quem_e_este_treinador"
    display_name = "Quem É Este Treinador?"
    implemented = False

    def build_copy(self, player: Player, clue: str, difficulty: Difficulty) -> QuizCopy:
        raise NotImplementedError(
            "«Quem É Este Treinador?» ainda não está publicado. "
            "Precisa de uma base de treinadores (não de jogadores). Ver README."
        )


register(QuemEEsteTreinadorFormat())
