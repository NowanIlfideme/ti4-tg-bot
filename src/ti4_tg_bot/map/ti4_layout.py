"""Layout for a TI4 map (to generate)."""

from typing_extensions import Annotated
from pydantic import BaseModel, Field, TypeAdapter, FieldValidationInfo, field_validator

from ti4_tg_bot.data.models import GameInfo
from .hexes import HexCoord
from .ti4_map import TIMaybeMap, PlaceholderTile


CoordLike = HexCoord | tuple[int, int] | tuple[int, int, int]
to_coord = TypeAdapter(HexCoord).validate_python


class TILayout(BaseModel):
    """Layout definition, with proper types."""

    name: str
    players: Annotated[int, Field(ge=2)]
    fixed_tiles: dict[HexCoord, int] = {}
    home_tiles: list[HexCoord]
    free_tiles: list[HexCoord]

    @field_validator("home_tiles", mode="after")
    @classmethod
    def _check_home_tiles(
        cls, v: list[HexCoord], info: FieldValidationInfo
    ) -> list[HexCoord]:
        """Ensure home tiles are correct."""
        players = info.data["players"]
        if len(v) != players:
            raise ValueError(f"Expected {players} home tiles, got: {len(v)}")
        return v

    def to_maybe_map(self, game_info: GameInfo) -> TIMaybeMap:
        """Convert to map."""
        cells = {}
        num_to_tile = {x.number: x for x in game_info.tiles.all_tiles}
        # Set free tiles
        for coord in self.free_tiles:
            cells[coord] = PlaceholderTile(is_home=False)
        # Set home tiles
        for coord in self.home_tiles:
            cells[coord] = PlaceholderTile(is_home=True)
        # Set fixed tiles
        for coord, tile_num in self.fixed_tiles.items():
            cells[coord] = num_to_tile[tile_num]
        return TIMaybeMap(cells=cells)


class _FixedTile(BaseModel):
    """A fixed tile."""

    at: CoordLike
    number: int
    # Maybe allow names too? Though tiles don't really have names.


class YamlTILayout(BaseModel):
    """Layout definition in YAML.

    This is only needed for YAML schema checking.
    Technically the schema can be updated manually, but... not yet good enough for that.
    """

    name: str
    players: Annotated[int, Field(ge=2)]
    fixed_tiles: list[_FixedTile] = []
    home_tiles: list[CoordLike]
    free_tiles: list[CoordLike]

    def fix_layout(self) -> TILayout:
        """Convert to proper layout."""
        fixed_tiles = {to_coord(ft.at): ft.number for ft in self.fixed_tiles}
        home_tiles = [to_coord(ht) for ht in self.home_tiles]
        free_tiles = [to_coord(ft) for ft in self.free_tiles]
        return TILayout(
            name=self.name,
            players=self.players,
            fixed_tiles=fixed_tiles,
            home_tiles=home_tiles,
            free_tiles=free_tiles,
        )

    @field_validator("home_tiles", mode="after")
    @classmethod
    def _check_home_tiles(
        cls, v: list[CoordLike], info: FieldValidationInfo
    ) -> list[CoordLike]:
        """Ensure home tiles are correct."""
        players = info.data["players"]
        if len(v) != players:
            raise ValueError(f"Expected {players} home tiles, got: {len(v)}")
        return v
