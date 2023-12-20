"""Milty draft approximation."""

import warnings
from collections import Counter
from pathlib import Path
from random import Random
from typing import Annotated, Any, Literal

from PIL.Image import Image
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
    FieldValidationInfo,
)
from pydantic_core import ValidationError

from ti4_tg_bot.data.models import Tile, TechSpecialty, TileSet, Wormhole
from ti4_tg_bot.map.hexes import HexCoord
from ti4_tg_bot.map.ti4_map import TIMaybeMap, PlaceholderTile, TextMapAnnotation


class ApproxValue(BaseModel):
    """Approximate value of a planet/tile/slice."""

    resources: float = 0
    influence: float = 0
    misc: float = 0

    @property
    def total(self) -> float:
        """Total value."""
        return self.resources + self.influence + self.misc

    def __add__(self, av: "ApproxValue") -> "ApproxValue":
        """Add values."""
        if not isinstance(av, ApproxValue):
            return NotImplemented
        return ApproxValue(
            resources=self.resources + av.resources,
            influence=self.influence + av.influence,
            misc=self.misc + av.misc,
        )

    @property
    def human_description(self) -> str:
        """Human-readable description of the approximate value."""
        return (
            f"{self.total:5.2f} ({self.resources:5.2f} R + "
            f"{self.influence:5.2f} I + {self.misc:5.2f} E)"
        )


SkipValues = dict[TechSpecialty, float]
DEFAULT_SKIP_VALUES: SkipValues = {
    TechSpecialty.NO_TECH: 0,
    TechSpecialty.BLUE: 0.25,
    TechSpecialty.GREEN: 0.2,
    TechSpecialty.YELLOW: 0.15,
    TechSpecialty.RED: 0.1,
}


def evaluate_tile(
    tile: Tile, *, skip_values: SkipValues = DEFAULT_SKIP_VALUES
) -> ApproxValue:
    """Get the 'optimal' use value of planets in the tile."""
    v_res = 0.0
    v_inf = 0.0
    v_misc = 0.0
    for planet in tile.planets:
        # Resources and influence
        ri, ii = planet.resources, planet.influence
        if ri > ii:
            v_res += ri
        elif ri < ii:
            v_inf += ii
        else:
            v_res += ri / 2
            v_inf += ii / 2
        # Misc calculation
        v_misc += skip_values.get(planet.tech, 0.0)
    return ApproxValue(resources=v_res, influence=v_inf, misc=v_misc)


class MiltyMapSlice(BaseModel):
    """Map slice for Milty-style draft."""

    home: Tile | None = None
    # mecatol: Tile
    close_left: Tile
    close_mid: Tile
    close_right: Tile
    far_left: Tile
    far_mid: Tile

    @classmethod
    def from_list(cls, tiles: list[Tile]) -> "MiltyMapSlice":
        """Create a map slice from list of tiles."""
        if len(tiles) == 5:
            home = None
        elif len(tiles) == 6:
            home = tiles[5]
        else:
            raise ValueError(f"Require 5 or 6 tiles, got: {tiles!r}")
        return MiltyMapSlice(
            close_left=tiles[0],
            close_mid=tiles[1],
            close_right=tiles[2],
            far_left=tiles[3],
            far_mid=tiles[4],
            home=home,
        )

    @property
    def tiles(self) -> list[Tile]:
        """Tiles, not including home system."""
        return [
            self.close_left,
            self.close_mid,
            self.close_right,
            self.far_left,
            self.far_mid,
        ]

    def to_tile_dict(
        self, rotations: int = 0
    ) -> dict[HexCoord, Tile | PlaceholderTile]:
        """Convert tiles to dictionary, including possible rotation."""
        res: dict[HexCoord, Tile | PlaceholderTile] = {}
        if self.home is None:
            res[HexCoord(root=(0, -3, 3))] = PlaceholderTile()
        else:
            res[HexCoord(root=(0, -3, 3))] = self.home
        res[HexCoord(root=(-1, -2, 3))] = self.close_left
        res[HexCoord(root=(0, -2, 2))] = self.close_mid
        res[HexCoord(root=(1, -3, 2))] = self.close_right
        res[HexCoord(root=(-1, -1, 2))] = self.far_left
        res[HexCoord(root=(0, -1, 1))] = self.far_mid

        # Rotate
        for _ in range(rotations):
            res = {hc.rotate_clockwise_60(): t for (hc, t) in res.items()}
        return res

    def evaluate_slice(self) -> ApproxValue:
        """Evaluate constituent tiles."""
        res = ApproxValue()
        for tile in self.tiles:
            res = res + evaluate_tile(tile)
        return res


class MiltyDraftState(BaseModel):
    """The state of a Milty draft."""

    model_config = ConfigDict(validate_assignment=True)

    n_players: Literal[6] = 6
    slices: Annotated[list[MiltyMapSlice], Field(min_length=6, max_length=6)]  # for now
    player_names: dict[int, str] = {}
    player_order: dict[int, int] = {}
    player_slices: dict[int, int] = {}
    player_homes: dict[int, Tile] = {}
    # Other things needed
    mecatol: Tile

    # Validators

    @field_validator(
        "player_names", "player_order", "player_slices", "player_homes", mode="after"
    )
    @classmethod
    def _chk_player_idx(
        cls, v: dict[int, Any], info: FieldValidationInfo
    ) -> dict[int, Any]:
        """Ensure player index is within the range."""
        n_players = info.data["n_players"]
        for k in v.keys():
            if k not in range(n_players):
                raise ValueError(f"Value not within range [0, {n_players})")
        return v

    @field_validator("slices", mode="after")
    @classmethod
    def _chk_slices(cls, v: list[MiltyMapSlice]) -> list[MiltyMapSlice]:
        """Check slice individually."""
        for i, slice in enumerate(v):
            # Ensure there aren't double wormholes in systems
            wormholes: Counter[Wormhole] = Counter()
            for tile in slice.tiles:
                wormholes[tile.wormhole] += 1
            for wht in list(Wormhole):
                if wht == Wormhole.NO_WORMHOLE:
                    continue
                if wormholes[wht] > 1:
                    raise ValueError(f"Too many {wht.name} wormholes in slice {i}")
        return v

    # Methods

    @classmethod
    def make_random(
        cls,
        tileset: TileSet,
        *,
        seed: Random | int | None = None,
        n_slices: Literal[6] = 6,  # only 6 slices supported for now
        n_reds: Literal[2] = 2,  # 2 blue tiles
        n_blues: Literal[3] = 3,  # 3 blue tiles
        retries: int = 5,
    ) -> tuple["MiltyDraftState", Random]:
        """Make a random draft state from a tileset, seed and settings."""
        if retries < 0:  # if we have a negative amount of retries, we're out
            raise RuntimeError("Ran out of retries when generating.")

        if isinstance(seed, Random):
            # clone
            rng = Random()
            rng.setstate(seed.getstate())
        else:
            rng = Random(seed)

        # Create and shuffle initial tile sets
        reds = list(tileset.red_tiles)
        rng.shuffle(reds)
        blues = list(tileset.blue_tiles)
        rng.shuffle(blues)

        slices: list[MiltyMapSlice] = []
        for i in range(n_slices):
            raw_i = (
                reds[n_reds * i : n_reds * (i + 1)]
                + blues[n_blues * i : n_blues * (i + 1)]
            )
            rng.shuffle(raw_i)
            slices.append(MiltyMapSlice.from_list(raw_i))

        # Create slice collection
        # NOTE: Might fail entirely - we will just regenerate, if we have retries
        try:
            res = cls(slices=slices, mecatol=tileset.mecatol)
        except ValidationError:
            try:
                res, rng = cls.make_random(
                    tileset=tileset,
                    seed=rng,
                    retries=retries - 1,  # one less retry
                    n_slices=n_slices,
                    n_reds=n_reds,
                    n_blues=n_blues,
                )
            except RuntimeError as rte:
                raise RuntimeError(
                    f"Could not make map within {retries} retries from seed {seed}"
                ) from rte

        return res, rng

    def to_map(self) -> TIMaybeMap:
        """Create a map from the draft state. Might fail/warn..."""
        N = self.n_players
        if len(self.player_order) != N:
            warnings.warn("Player order is not fully set.")
        if len(self.player_slices) != N:
            warnings.warn("Player slices are not fully set.")
        if len(self.player_homes) != N:
            warnings.warn("Player homes are not fully set.")

        cells = {}
        annots: list[TextMapAnnotation] = []

        # Pre-set homes as placeholders
        for z in range(N):
            place_coord = HexCoord(root=(0, -3, 3))
            for _ in range(z):
                place_coord = place_coord.rotate_clockwise_60()
            cells[place_coord] = PlaceholderTile()

        # Place the slices
        for i in range(N):
            try:
                name_i = self.player_names.get(i, f"player_{i}")
                order_i = self.player_order[i]
                slice_i = self.slices[self.player_slices[i]].model_copy(deep=True)

                # Set home slice (is this needed?)
                if i in self.player_homes:
                    slice_i.home = self.player_homes[i]

                cells.update(slice_i.to_tile_dict(rotations=order_i))

                # Add player labels
                place_coord = HexCoord(root=(0, -3, 3))
                for _ in range(order_i):
                    place_coord = place_coord.rotate_clockwise_60()

                av = slice_i.evaluate_slice()
                res_vals_i = av.human_description
                annots += [
                    TextMapAnnotation(cell=place_coord, text=name_i),
                    TextMapAnnotation(
                        cell=place_coord,
                        text=res_vals_i,
                        offset=(0, 80),
                        font_size=40,
                    ),
                ]
            except Exception as exc:
                warnings.warn(f"Failed to set player {i}:\n{exc!r}")
                # raise  # should we do that?...

        # Add mecatol
        cells[HexCoord(root=(0, 0, 0))] = self.mecatol.model_copy(deep=True)

        return TIMaybeMap(cells=cells, annotations=annots)

    def visualize_slices(self, base_path: Path) -> list[Image]:
        """Visualize slices."""
        res: list[Image] = []
        for i, slice in enumerate(self.slices):
            cells_i = slice.to_tile_dict()
            cells_i[HexCoord(root=(0, 0, 0))] = self.mecatol
            xc = HexCoord(root=(0, -3, 3))
            annot_i = [
                TextMapAnnotation(cell=xc, text=f"Slice {i}"),
                TextMapAnnotation(
                    cell=xc,
                    text=slice.evaluate_slice().human_description,
                    offset=(0, 80),
                    font_size=40,
                ),
            ]
            part_i = TIMaybeMap(cells=cells_i, annotations=annot_i)
            res.append(part_i.to_image(base_path))
        return res
