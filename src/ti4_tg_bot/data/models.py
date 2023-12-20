"""Data models."""

from enum import Enum

from pydantic import BaseModel, HttpUrl, model_validator


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

    @property
    def all_tiles(self) -> list[Tile]:
        """Get all tiles as a list, sorted by number."""
        raw = [self.mecatol] + self.blue_tiles + self.red_tiles + self.home_tiles
        res = sorted(raw, key=lambda x: x.number)
        return res

    def get_faction_home(self, faction_name: str) -> Tile:
        """Get the home tile for some faction."""
        found = [ht for ht in self.home_tiles if ht.race == faction_name]
        if len(found) != 1:
            raise ValueError(f"Unknown or ambigious faction name: {faction_name}")
        return found[0]

    def get_by_number(self, num: int) -> Tile:
        """Get a tile by number."""
        for tile in self.all_tiles:
            if tile.number == num:
                return tile
        raise ValueError(f"No tile exists for number: {num}")

    def __getitem__(self, val: int) -> Tile:
        """Get a tile by number (dict style)."""
        try:
            return self.get_by_number(val)
        except ValueError as ve:
            raise KeyError(val) from ve


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

    @model_validator(mode="after")
    def _chk_faction_tiles(self) -> "GameInfo":
        """Ensure faction tiles correspond to the factions."""
        tile_races = {ht.race for ht in self.tiles.home_tiles}
        fns = set(self.faction_names)
        if tile_races != fns:
            raise ValueError(
                f"Faction mismatch: {tile_races - fns}, {fns - tile_races}"
            )

        return self
