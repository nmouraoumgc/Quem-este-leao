from __future__ import annotations

from quem_e_este_leao.clues import contains_identity, generate_clue
from quem_e_este_leao.config import Difficulty
from quem_e_este_leao.players import load_players


def test_clue_never_contains_player_name(tmp_settings) -> None:
    players = load_players(tmp_settings.players_yaml)
    assert len(players) >= 28
    for player in players:
        for diff in Difficulty:
            clue = generate_clue(player, diff)
            assert clue.strip()
            assert not contains_identity(clue, player), (player.display_name, clue)
            for token in player.identity_tokens:
                if len(token) >= 4:
                    assert token.casefold() not in clue.casefold(), (token, clue)


def test_easy_clue_is_simple(tmp_settings) -> None:
    from tests.helpers import make_player

    player = make_player()
    clue = generate_clue(player, Difficulty.EASY)
    assert "LeaozinhoUnico" not in clue
    assert "Teste" not in clue
