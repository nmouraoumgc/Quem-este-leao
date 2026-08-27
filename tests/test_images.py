from __future__ import annotations

import pytest

from quem_e_este_leao.images import (
    sporting_search_queries,
    wikimedia_filename_wrong_era,
)
from quem_e_este_leao.players import get_player, load_players
from quem_e_este_leao.processing import AnonymizationError
from quem_e_este_leao.quiz import generate_quiz
from quem_e_este_leao.config import Difficulty
from tests.helpers import make_player


def test_search_queries_include_sporting_and_years() -> None:
    figo = make_player(
        id="luis-figo",
        display_name="Luís Figo",
        years_at_sporting="1989–1995",
        image_search_query="Luís Figo career",
    )
    queries = sporting_search_queries(figo)
    assert queries
    assert all("sporting" in q.casefold() for q in queries)
    assert any("1995" in q for q in queries)
    assert any("Sporting CP" in q for q in queries)
    # consulta genérica da carreira NÃO é primária
    assert queries[0] != "Luís Figo career"


def test_gyokeres_query_uses_sporting_year() -> None:
    p = make_player(
        id="viktor-gyokeres",
        display_name="Viktor Gyökeres",
        years_at_sporting="2023–2025",
        image_search_query="Viktor Gyökeres football",
    )
    queries = sporting_search_queries(p)
    blob = " ".join(queries)
    assert "Sporting" in blob
    assert "2024" in blob or "2025" in blob
    assert queries[0] != "Viktor Gyökeres football"


def test_wikimedia_filename_other_club_year_is_skipped() -> None:
    gyok = make_player(
        id="viktor-gyokeres",
        display_name="Viktor Gyökeres",
        years_at_sporting="2023–2025",
    )
    figo = make_player(
        id="luis-figo",
        display_name="Luís Figo",
        years_at_sporting="1989–1995",
    )
    nuno = make_player(
        id="nuno-santos",
        display_name="Nuno Santos",
        years_at_sporting="2020–",
    )
    assert wikimedia_filename_wrong_era("Viktor Gyökeres 2018.jpg", gyok)
    assert wikimedia_filename_wrong_era(
        "Football against poverty 2014 - Luis Figo.jpg", figo
    )
    assert not wikimedia_filename_wrong_era("Portrait - Nuno Santos.jpg", nuno)
    assert not wikimedia_filename_wrong_era("Pedro Porro 2021.png", nuno)


def test_figo_poverty_photo_is_not_used_in_production(
    tmp_settings, tmp_path, project_root
) -> None:
    from dataclasses import replace

    players = load_players(tmp_settings.players_yaml)
    figo = get_player(players, "luis-figo")
    figo = replace(
        figo,
        local_image=str(project_root / "tests" / "fixtures" / "not_sporting_kit.jpg"),
        wikimedia_filename=None,
    )
    with pytest.raises(AnonymizationError):
        generate_quiz(
            tmp_settings,
            difficulty=Difficulty.MEDIUM,
            player=figo,
            allow_synthetic=False,
            output_dir=tmp_path,
        )


def test_figo_without_sporting_photo_is_skipped(tmp_settings, tmp_path) -> None:
    players = load_players(tmp_settings.players_yaml)
    figo = get_player(players, "luis-figo")
    assert not figo.local_image
    with pytest.raises(AnonymizationError):
        generate_quiz(
            tmp_settings,
            difficulty=Difficulty.MEDIUM,
            player=figo,
            allow_synthetic=False,
            output_dir=tmp_path,
        )
