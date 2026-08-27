"""Esqueleto: «Quem Usava Esta Camisola?»."""

from __future__ import annotations

from quem_e_este_leao.config import Difficulty
from quem_e_este_leao.formats.base import QuizCopy, QuizFormat, register
from quem_e_este_leao.players import Player


class QuemUsavaEstaCamisolaFormat(QuizFormat):
    id = "quem_usava_esta_camisola"
    display_name = "Quem Usava Esta Camisola?"
    implemented = False

    def build_copy(self, player: Player, clue: str, difficulty: Difficulty) -> QuizCopy:
        raise NotImplementedError(
            "«Quem Usava Esta Camisola?» ainda não está publicado. "
            "A imagem herói seria a camisola, não o jogador. Ver README."
        )


register(QuemUsavaEstaCamisolaFormat())
