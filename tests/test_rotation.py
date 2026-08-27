from __future__ import annotations

import random

from quem_e_este_leao import db
from quem_e_este_leao.players import Player
from tests.helpers import make_player


def _pool() -> list[Player]:
    return [
        make_player(id="a", display_name="Jogador Alfa"),
        make_player(id="b", display_name="Jogador Beta"),
        make_player(id="c", display_name="Jogador Gama"),
    ]


def test_no_repeat_until_pool_exhausted(tmp_settings) -> None:
    players = _pool()
    rng = random.Random(0)
    seen: list[str] = []
    with db.session(tmp_settings.database_path) as conn:
        for _ in range(3):
            chosen = db.select_player(conn, players, rng)
            seen.append(chosen.id)
        assert set(seen) == {"a", "b", "c"}
        assert db.current_cycle(conn) == 1
        # quarto: novo ciclo, pode repetir
        fourth = db.select_player(conn, players, rng)
        assert fourth.id in {"a", "b", "c"}
        assert db.current_cycle(conn) == 2


def test_exclude_skips_failed_candidates(tmp_settings) -> None:
    players = _pool()
    rng = random.Random(1)
    with db.session(tmp_settings.database_path) as conn:
        first = db.select_player(conn, players, rng)
        second = db.select_player(conn, players, rng, exclude={first.id})
        assert second.id != first.id
