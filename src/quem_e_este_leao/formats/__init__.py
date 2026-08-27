"""Formatos de quiz extensíveis."""

from __future__ import annotations

from quem_e_este_leao.formats.base import QuizFormat, get_format, list_formats
from quem_e_este_leao.formats import (  # noqa: F401  — registo por side-effect
    de_que_epoca,
    quem_e_esta_lenda,
    quem_e_este_leao,
    quem_e_este_treinador,
    quem_marcou_este_golo,
    quem_usava_esta_camisola,
)

__all__ = ["QuizFormat", "get_format", "list_formats"]
