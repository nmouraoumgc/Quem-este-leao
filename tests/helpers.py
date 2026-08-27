from __future__ import annotations

from quem_e_este_leao.players import Player


def make_player(**overrides: object) -> Player:
    base: dict = dict(
        id="teste-leao",
        display_name="Teste Leão",
        nationality="Portugal",
        position="avançado",
        years_at_sporting="2020–2024",
        shirt_numbers=(9,),
        achievements=("Campeão nacional em 2020/21",),
        fun_facts=("Golo ao minuto 90.",),
        image_search_query="Teste Leao Sporting",
        wikimedia_filename=None,
        local_image=None,
        nicknames=("LeaozinhoUnico",),
        national_team=True,
        academy=True,
    )
    base.update(overrides)
    return Player(**base)  # type: ignore[arg-type]
