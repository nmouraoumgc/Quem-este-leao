"""Logging: a resposta correcta só pode aparecer em DEBUG, nunca em INFO."""

from __future__ import annotations

import logging
import sys
from typing import Any


ANSWER_LOGGER_NAME = "quem_e_este_leao.answer"


class _NeverInfoAnswerFilter(logging.Filter):
    """Rebaixa qualquer registo INFO (ou superior) do logger de respostas."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name == ANSWER_LOGGER_NAME and record.levelno >= logging.INFO:
            record.levelno = logging.DEBUG
            record.levelname = "DEBUG"
        return True


def setup_logging(level: str = "INFO") -> None:
    root = logging.getLogger("quem_e_este_leao")
    if root.handlers:
        root.setLevel(getattr(logging, level.upper(), logging.INFO))
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    handler.addFilter(_NeverInfoAnswerFilter())
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.propagate = False

    answer = logging.getLogger(ANSWER_LOGGER_NAME)
    answer.setLevel(logging.DEBUG)
    answer.addFilter(_NeverInfoAnswerFilter())


def get_logger(name: str) -> logging.Logger:
    if not name.startswith("quem_e_este_leao"):
        name = f"quem_e_este_leao.{name}"
    return logging.getLogger(name)


def log_answer(message: str, *args: Any) -> None:
    """Único sítio autorizado para mencionar o jogador — sempre DEBUG."""
    logging.getLogger(ANSWER_LOGGER_NAME).debug(message, *args)
