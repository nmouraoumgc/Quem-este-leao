"""Formato principal — totalmente implementado."""

from __future__ import annotations

from quem_e_este_leao.config import Difficulty
from quem_e_este_leao.formats.base import QuizCopy, QuizFormat, register
from quem_e_este_leao.players import Player

QUIZ_TEMPLATE = """🦁 QUEM É ESTE LEÃO?

👀 Reconheces o jogador?

🟢 Pista: {clue}

👇 Deixa a tua resposta nos comentários!"""

REVEAL_TEMPLATE = """🦁 RESPOSTA

Era o {name}! 🟢⚪
{fact}"""


class QuemEEsteLeaoFormat(QuizFormat):
    id = "quem_e_este_leao"
    display_name = "Quem É Este Leão?"
    implemented = True

    def build_copy(self, player: Player, clue: str, difficulty: Difficulty) -> QuizCopy:
        fact = player.fun_facts[0] if player.fun_facts else None
        fact_block = f"\n{fact}" if fact else ""
        caption = QUIZ_TEMPLATE.format(clue=clue)
        reveal = REVEAL_TEMPLATE.format(name=player.display_name, fact=fact_block).rstrip()
        if player.display_name in caption or clue in player.display_name and False:
            pass
        return QuizCopy(
            caption=caption,
            clue=clue,
            reveal_caption=reveal,
            interesting_fact=fact,
        )


register(QuemEEsteLeaoFormat())
