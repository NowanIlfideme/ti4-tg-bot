"""Data models."""

from enum import Enum

from pydantic import BaseModel, HttpUrl


class Wormhole(str, Enum):
    """Wormhole type."""

    NO_WORMHOLE = "NO_WORMHOLE"
    ALPHA = "ALPHA"
    BETA = "BETA"
    # GAMMA = "GAMMA"
    # DELTA = "DELTA"  # not used for TI4 base game


class Anomaly(str, Enum):
    """Anomaly type (including empty systems)."""

    NO_ANOMALY = "NO_ANOMALY"
    EMPTY = "EMPTY"
    GRAVITY_RIFT = "GRAVITY_RIFT"
    NEBULA = "NEBULA"
    ASTEROID_FIELD = "ASTEROID_FIELD"
    SUPERNOVA = "SUPERNOVA"


class PlanetTrait(str, Enum):
    """Planet trait."""

    NO_TRAIT = "NO_TRAIT"  # Mecatol and home worlds
    CULTURAL = "CULTURAL"
    HAZARDOUS = "HAZARDOUS"
    INDUSTRIAL = "INDUSTRIAL"


class TechSpecialty(str, Enum):
    """Tech specialty (skip)."""

    NO_TECH = "NO_TECH"
    GREEN = "GREEN"
    RED = "RED"
    YELLOW = "YELLOW"
    BLUE = "BLUE"


class Planet(BaseModel):
    """Planet information."""

    name: str
    resources: int
    influence: int
    trait: PlanetTrait = PlanetTrait.NO_TRAIT
    tech: TechSpecialty = TechSpecialty.NO_TECH


class Tile(BaseModel):
    """Tile information."""

    number: int
    race: str | None = None  # for home worlds
    wormhole: Wormhole = Wormhole.NO_WORMHOLE
    anomaly: Anomaly = Anomaly.NO_ANOMALY
    planets: list[Planet] = []


class TileSet(BaseModel):
    """Tile set."""

    mecatol: Tile
    blue_tiles: list[Tile]
    red_tiles: list[Tile]
    home_tiles: list[Tile]


class Faction(BaseModel):
    """Faction information."""

    name: str
    wiki: HttpUrl


class GameInfo(BaseModel):
    """Game setup info."""

    min_players: int
    max_players: int
    factions: list[Faction]
    tiles: TileSet

    @property
    def faction_names(self) -> list[str]:
        """Faction names."""
        return [x.name for x in self.factions]
