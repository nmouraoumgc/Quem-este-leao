"""Carregamento da base de jogadores (YAML)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from quem_e_este_leao.logging_setup import get_logger

log = get_logger("players")


@dataclass(frozen=True)
class Player:
    id: str
    display_name: str
    nationality: str
    position: str
    years_at_sporting: str
    shirt_numbers: tuple[int, ...]
    achievements: tuple[str, ...]
    fun_facts: tuple[str, ...]
    image_search_query: str
    wikimedia_filename: str | None = None
    local_image: str | None = None
    nicknames: tuple[str, ...] = ()
    national_team: bool = False
    academy: bool = False

    @property
    def identity_tokens(self) -> tuple[str, ...]:
        """Tokens que nunca podem aparecer em pistas, ficheiros ou legendas públicas."""
        tokens: list[str] = [self.display_name, *self.nicknames]
        for part in self.display_name.replace("-", " ").split():
            if len(part) >= 3:
                tokens.append(part)
        # id hyphenated pieces (gyokeres, etc.)
        for part in self.id.split("-"):
            if len(part) >= 4:
                tokens.append(part)
        # unique set, keep order
        seen: set[str] = set()
        out: list[str] = []
        for t in tokens:
            key = t.casefold()
            if key not in seen:
                seen.add(key)
                out.append(t)
        return tuple(out)


def _as_tuple_str(value: Any) -> tuple[str, ...]:
    if not value:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(v) for v in value)


def _as_tuple_int(value: Any) -> tuple[int, ...]:
    if not value:
        return ()
    return tuple(int(v) for v in value)


def player_from_dict(raw: dict[str, Any]) -> Player:
    return Player(
        id=str(raw["id"]),
        display_name=str(raw["display_name"]),
        nationality=str(raw["nationality"]),
        position=str(raw["position"]),
        years_at_sporting=str(raw["years_at_sporting"]),
        shirt_numbers=_as_tuple_int(raw.get("shirt_numbers") or ()),
        achievements=_as_tuple_str(raw.get("achievements") or ()),
        fun_facts=_as_tuple_str(raw.get("fun_facts") or ()),
        image_search_query=str(raw.get("image_search_query") or raw["display_name"]),
        wikimedia_filename=raw.get("wikimedia_filename") or None,
        local_image=raw.get("local_image") or None,
        nicknames=_as_tuple_str(raw.get("nicknames") or ()),
        national_team=bool(raw.get("national_team") or False),
        academy=bool(raw.get("academy") or False),
    )


def load_players(path: Path) -> list[Player]:
    if not path.exists():
        raise FileNotFoundError(f"Ficheiro de jogadores não encontrado: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not data or "players" not in data:
        raise ValueError(f"YAML inválido: falta a chave 'players' em {path}")
    players = [player_from_dict(item) for item in data["players"]]
    ids = [p.id for p in players]
    if len(ids) != len(set(ids)):
        raise ValueError("IDs de jogadores duplicados na base.")
    log.info("Carregados %s jogadores de %s", len(players), path.name)
    return players


def get_player(players: list[Player], player_id: str) -> Player:
    for p in players:
        if p.id == player_id:
            return p
    raise KeyError(f"Jogador desconhecido: {player_id}")
