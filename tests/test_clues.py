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

def test_easy_combo_not_unique_identifier() -> None:
    from quem_e_este_leao.clues import combo_uniquely_identifies, generate_clue
    from tests.helpers import make_player

    unique = make_player(id="sueco", display_name="Sven Teste", nationality="Suécia", position="avançado")
    others = [
        make_player(id="p1", display_name="Outro Um", nationality="Portugal", position="médio"),
        make_player(id="p2", display_name="Outro Dois", nationality="Espanha", position="extremo"),
    ]
    pool = [unique, *others]
    assert combo_uniquely_identifies(unique, pool, nationality=True, position=True)
    clue = generate_clue(unique, Difficulty.EASY, pool=pool)
    assert "Sven" not in clue
    assert "Teste" not in clue

