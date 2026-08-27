"""Esqueleto: «Quem Marcou Este Golo?»."""

from __future__ import annotations

from quem_e_este_leao.config import Difficulty
from quem_e_este_leao.formats.base import QuizCopy, QuizFormat, register
from quem_e_este_leao.players import Player


class QuemMarcouEsteGoloFormat(QuizFormat):
    id = "quem_marcou_este_golo"
    display_name = "Quem Marcou Este Golo?"
    implemented = False

    def build_copy(self, player: Player, clue: str, difficulty: Difficulty) -> QuizCopy:
        raise NotImplementedError(
            "«Quem Marcou Este Golo?» ainda não está publicado. "
            "Exigirá um arquivo de golos com direitos de imagem. Ver README."
        )


register(QuemMarcouEsteGoloFormat())
