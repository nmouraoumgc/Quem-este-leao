"""Interface QuizFormat e registo."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from quem_e_este_leao.config import Difficulty
    from quem_e_este_leao.players import Player


@dataclass
class QuizCopy:
    caption: str
    clue: str
    reveal_caption: str
    interesting_fact: str | None


class QuizFormat(ABC):
    id: str
    display_name: str
    implemented: bool = False

    @abstractmethod
    def build_copy(self, player: Player, clue: str, difficulty: Difficulty) -> QuizCopy:
        raise NotImplementedError

    def describe(self) -> str:
        estado = "activo" if self.implemented else "esqueleto (ainda não publicado)"
        return f"{self.display_name} [{self.id}] — {estado}"


_REGISTRY: dict[str, QuizFormat] = {}


def register(fmt: QuizFormat) -> QuizFormat:
    _REGISTRY[fmt.id] = fmt
    return fmt


def get_format(format_id: str) -> QuizFormat:
    if format_id not in _REGISTRY:
        # import lazy para preencher o registo
        from quem_e_este_leao.formats import (  # noqa: F401
            de_que_epoca,
            quem_e_esta_lenda,
            quem_e_este_leao,
            quem_e_este_treinador,
            quem_marcou_este_golo,
            quem_usava_esta_camisola,
        )

        _ = (
            quem_e_este_leao,
            quem_e_esta_lenda,
            quem_marcou_este_golo,
            de_que_epoca,
            quem_usava_esta_camisola,
            quem_e_este_treinador,
        )
    if format_id not in _REGISTRY:
        known = ", ".join(sorted(_REGISTRY)) or "(vazio)"
        raise KeyError(f"Formato desconhecido: {format_id}. Disponíveis: {known}")
    return _REGISTRY[format_id]


def list_formats() -> list[QuizFormat]:
    get_format("quem_e_este_leao")  # força o import
    return list(_REGISTRY.values())
