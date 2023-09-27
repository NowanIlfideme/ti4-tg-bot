"""Data models for the map."""

from pydantic import BaseModel
from .models import Tile

Idx = tuple[int, int]
Adj = tuple[Idx, Idx]


class GalaxyShape(BaseModel):
    """The shape of a galaxy."""

    valid_positions: list[Idx]
    home_positions: dict[int, list[Idx]]  # per player count
    hyper_lanes: list[Adj] = []


class GalaxyLayout(GalaxyShape):
    """A pre-set layout."""

    layout_name: str


class UnsetTile(Tile):
    """Unset placeholder tile."""


class PlayerTile(UnsetTile):
    """Tile assigned to a player, but otherwise unset."""

    player: str


class GalaxyTiles(BaseModel):
    """Define a galaxy with tiles.

    State might be empty, in-progress or completed.
    """
