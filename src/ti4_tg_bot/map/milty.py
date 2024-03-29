"""Milty draft approximation."""

import logging
from collections import Counter
from pathlib import Path
from random import Random
from typing import Annotated, Any, Literal, cast

from PIL.Image import Image
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    FieldValidationInfo,
)
from pydantic_core import ValidationError

from ti4_tg_bot.data.models import Faction, Tile, TechSpecialty, TileSet, Wormhole
from ti4_tg_bot.map.hexes import HexCoord
from ti4_tg_bot.map.ti4_map import TIMaybeMap, PlaceholderTile, TextMapAnnotation


logger = logging.getLogger(__name__)


class ApproxValue(BaseModel):
    """Approximate value of a planet/tile/slice."""

    eff_resources: float = 0
    eff_influence: float = 0
    misc: float = 0

    strict_resources: int = 0
    strict_influence: int = 0

    @property
    def total(self) -> float:
        """Total value."""
        return self.eff_resources + self.eff_influence + self.misc

    def __add__(self, av: "ApproxValue") -> "ApproxValue":
        """Add values."""
        if not isinstance(av, ApproxValue):
            return NotImplemented
        return ApproxValue(
            eff_resources=self.eff_resources + av.eff_resources,
            eff_influence=self.eff_influence + av.eff_influence,
            misc=self.misc + av.misc,
            strict_resources=self.strict_resources + av.strict_resources,
            strict_influence=self.strict_influence + av.strict_influence,
        )

    @property
    def human_description(self) -> str:
        """Human-readable description of the approximate value."""
        return (
            f"{self.total:.2f} = "
            f"{self.eff_resources:.2f} ({self.strict_resources}) R + "
            f"{self.eff_influence:.2f} ({self.strict_influence}) I + "
            f"{self.misc:.2f} E)"
        )


SkipValues = dict[TechSpecialty, float]
DEFAULT_SKIP_VALUES: SkipValues = {
    TechSpecialty.NO_TECH: 0,
    TechSpecialty.RED: 0.1,
    TechSpecialty.YELLOW: 0.15,
    TechSpecialty.GREEN: 0.2,
    TechSpecialty.BLUE: 0.25,
}


def evaluate_tile(
    tile: Tile, *, skip_values: SkipValues = DEFAULT_SKIP_VALUES
) -> ApproxValue:
    """Get the 'optimal' use value of planets in the tile."""
    s_res = 0
    s_inf = 0
    v_res = 0.0
    v_inf = 0.0
    v_misc = 0.0
    for planet in tile.planets:
        # Resources and influence
        ri, ii = planet.resources, planet.influence
        s_res += ri
        s_inf += ii
        if ri > ii:
            v_res += ri
        elif ri < ii:
            v_inf += ii
        else:
            v_res += ri / 2
            v_inf += ii / 2
        # Misc calculation
        v_misc += skip_values.get(planet.tech, 0.0)
    return ApproxValue(
        eff_resources=v_res,
        eff_influence=v_inf,
        misc=v_misc,
        strict_resources=s_res,
        strict_influence=s_inf,
    )


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

    @tiles.setter
    def tiles(self, vals: list[Tile]):
        """Set tiles."""
        (
            self.close_left,
            self.close_mid,
            self.close_right,
            self.far_left,
            self.far_mid,
        ) = vals

    def swap_tile(self, original: Tile, updated: Tile) -> None:
        """Swap the original tile for a new one."""
        if original not in self.tiles:
            raise ValueError(f"No original tile exists in tiles: {self.tiles}")
        ttt = list(self.tiles)
        ttt[ttt.index(original)] = updated
        self.tiles = ttt

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

    def evaluate_slice(
        self, skip_values: SkipValues = DEFAULT_SKIP_VALUES
    ) -> ApproxValue:
        """Evaluate constituent tiles."""
        res = ApproxValue()
        for tile in self.tiles:
            res = res + evaluate_tile(tile, skip_values=skip_values)
        return res


class MiltyDraftState(BaseModel):
    """The state of a Milty draft."""

    model_config = ConfigDict(validate_assignment=True)

    n_players: Literal[6] = 6
    slices: Annotated[list[MiltyMapSlice], Field(min_length=6, max_length=6)]  # for now
    factions: list[Faction] = []
    faction_homes: list[Tile] = []
    mecatol: Tile  # just needed for display, yes it's hacky

    # Player choices
    player_names: dict[int, str] = {}
    player_order: dict[int, int] = {}
    player_slices: dict[int, int] = {}
    player_factions: dict[int, int] = {}

    # Other things needed

    @property
    def player_homes(self) -> dict[int, Tile]:
        """Create player homes from factions."""
        return {k: self.faction_homes[v] for k, v in self.player_factions.items()}

    @property
    def available_seats(self) -> list[int]:
        """Available seats (speaker order)."""
        return [x for x in range(self.n_players) if x not in self.player_order.values()]

    @property
    def available_factions(self) -> list[tuple[int, Faction, Tile]]:
        """Available factions (number, faction info, tile)."""
        indices = [
            x
            for x in range(len(self.factions))
            if x not in self.player_factions.values()
        ]
        return [(i, self.factions[i], self.faction_homes[i]) for i in indices]

    @property
    def available_slices(self) -> list[tuple[int, MiltyMapSlice]]:
        """Available slices."""
        indices = [
            x for x in range(self.n_players) if x not in self.player_slices.values()
        ]
        return [(i, self.slices[i]) for i in indices]

    @property
    def is_complete(self) -> bool:
        """Whether all choices have been made."""
        return (
            self.n_players
            == len(self.player_factions)
            == len(self.player_order)
            == len(self.player_slices)
        )

    # Validators

    @field_validator(
        "player_names", "player_order", "player_slices", "player_factions", mode="after"
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

            # Ensure that anomalies aren't next to each other
            # TODO: Implement.
            # FIXME: This might lead to way too many rejections - fix in generation?

        # TODO: Optionally (via flag) ensure that all wormhole tiles are placed
        return v

    # High level Methods

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
        # NOTE: Might be rejected - we will just try regenerating
        try:
            res = cls(slices=slices, mecatol=tileset.mecatol)
        except ValidationError:
            # Retry again, starting with current retry level
            logger.warn(f"Failed, trying again ({retries} retries left).")
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
            logger.info("Player order is not fully set.")
        if len(self.player_slices) != N:
            logger.info("Player slices are not fully set.")
        if len(self.player_homes) != N:
            logger.info("Player homes are not fully set.")

        cells = {}
        annots: list[TextMapAnnotation] = []

        # Pre-set homes as placeholders
        for z in range(N):
            place_coord = HexCoord(root=(0, -3, 3))
            for _ in range(z):
                place_coord = place_coord.rotate_clockwise_60()
            cells[place_coord] = PlaceholderTile()

        # Add information about each player
        for ip in range(N):
            name_i = self.player_names.get(ip, f"player_{ip}")
            # Only if the player has chosen a seating order...
            if ip in self.player_order:
                order_i = self.player_order[ip]

                # Add player label
                place_coord = HexCoord(root=(0, -3, 3))
                for _ in range(order_i):
                    place_coord = place_coord.rotate_clockwise_60()
                annots.append(TextMapAnnotation(cell=place_coord, text=name_i))

                # Add slice (if set)
                if ip in self.player_slices:
                    slice_i = self.slices[self.player_slices[ip]].model_copy(deep=True)
                    av = slice_i.evaluate_slice()
                    res_vals_i = av.human_description
                    #
                    cells.update(slice_i.to_tile_dict(rotations=order_i))
                    annots.append(
                        TextMapAnnotation(
                            cell=place_coord,
                            text=res_vals_i,
                            offset=(0, 80),
                            font_size=40,
                        )
                    )

                # Add home for faction (if set) - will override the slice :)
                if ip in self.player_homes:
                    cells[place_coord] = self.player_homes[ip]

        # Add mecatol
        cells[HexCoord(root=(0, 0, 0))] = self.mecatol.model_copy(deep=True)

        return TIMaybeMap(cells=cells, annotations=annots)

    # Visualization

    def visualize_slices(
        self, base_path: Path, only_available: bool = False
    ) -> list[Image]:
        """Visualize slices."""
        res: list[Image] = []
        for i, slice in enumerate(self.slices):
            if only_available and i in [x[0] for x in self.available_slices]:
                # skip unavailable slices (if option is on)
                continue
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

    def visualize_factions(
        self, base_path: Path, only_available: bool = False
    ) -> list[Image]:
        res: list[Image] = []
        if only_available:
            fac_tuples = self.available_factions
        else:
            fac_tuples = list(
                zip(range(len(self.factions)), self.factions, self.faction_homes)
            )
        for i, fac, home in fac_tuples:
            mmap = TIMaybeMap(
                cells={(0, 0, 0): home},  # type: ignore
                annotations=[
                    TextMapAnnotation(
                        cell=(0, 0, 0),  # type: ignore
                        offset=(0, 250),
                        text=fac.name,
                        font_size=50,
                    )
                ],
            )
            res.append(mmap.to_image(base_path))
        return res

    # Player choices

    def available_player_choices(
        self, player_num: int
    ) -> dict[str, int | Faction | MiltyMapSlice]:
        """The choices available to a player, possibly: seats, factions, slices."""
        res = {}
        if player_num not in self.player_order:
            for seat_i in self.available_seats:
                if seat_i == 0:
                    res["Speaker (Seat 0)"] = seat_i
                else:
                    res[f"Seat {seat_i}"] = seat_i
        if player_num not in self.player_slices:
            for sl_i, slice in self.available_slices:
                # res[f"slice_{sl_i}"] = slice
                ev = slice.evaluate_slice()
                eff_val = ev.total
                st_res = ev.strict_resources
                st_inf = ev.strict_influence
                res[f"Slice {sl_i} (~{eff_val:.2f}/{st_res}/{st_inf})"] = slice
        if player_num not in self.player_factions:
            for fac_i, fac, _ in self.available_factions:
                # res[f"faction_{fac_i}"] = fac
                res[fac.name] = fac
        return res

    def apply_player_choice(self, player_num: int, choice_name: str) -> None:
        """Apply player choice, given the name (see `available_player_choices`)."""
        av_choices = self.available_player_choices(player_num=player_num)
        choice = av_choices.get(choice_name, None)
        if choice is None:
            raise ValueError(f"Unknown choice: {choice_name!r}")

        if isinstance(choice, int):
            self.player_order[player_num] = choice
        elif isinstance(choice, Faction):
            fac_num = self.factions.index(choice)
            self.player_factions[player_num] = fac_num
        elif isinstance(choice, MiltyMapSlice):
            slice_num = self.slices.index(choice)
            self.player_slices[player_num] = slice_num

    def snake_order(self) -> list[int]:
        """Player numbers in 'snake' draft order."""
        z = list(range(self.n_players))
        return list(z) + list(reversed(z)) + list(z)


QtyName = Literal[
    "total", "eff_resources", "strict_resources", "eff_influence", "strict_influence"
]
# HACK: Yeah this is ugly but maybe refactor later lol


def get_tile_quantity(
    t: Tile, q_name: QtyName, skip_values: SkipValues = DEFAULT_SKIP_VALUES
) -> float:
    """Get quantity for a tile given by the q_name."""
    match q_name:
        case "total":
            return evaluate_tile(t, skip_values=skip_values).total
        case "eff_resources":
            return evaluate_tile(t, skip_values=skip_values).eff_resources
        case "eff_influence":
            return evaluate_tile(t, skip_values=skip_values).eff_influence
        case "strict_resources":
            return evaluate_tile(t, skip_values=skip_values).strict_resources
        case "strict_influence":
            return evaluate_tile(t, skip_values=skip_values).strict_influence
        case _:
            raise ValueError("Unknown quantity.")


def get_slice_quantity(
    s: MiltyMapSlice, q_name: QtyName, skip_values: SkipValues = DEFAULT_SKIP_VALUES
) -> float:
    """Get quantity for a slice given by the q_name."""
    match q_name:
        case "total":
            return s.evaluate_slice(skip_values=skip_values).total
        case "eff_resources":
            return s.evaluate_slice(skip_values=skip_values).eff_resources
        case "eff_influence":
            return s.evaluate_slice(skip_values=skip_values).eff_influence
        case "strict_resources":
            return s.evaluate_slice(skip_values=skip_values).strict_resources
        case "strict_influence":
            return s.evaluate_slice(skip_values=skip_values).strict_influence
        case _:
            raise ValueError("Unknown quantity.")


class SliceRebalancer(BaseModel):
    """Utility class for rebalancing slices."""

    min_value: float = 9
    min_eff_resources: float | None = None  # FIXME: Doesn't work yet
    min_eff_influence: float | None = None  # FIXME: Doesn't work yet
    min_strict_resources: float | None = None  # FIXME: Doesn't work yet
    min_strict_influence: float | None = None  # FIXME: Doesn't work yet
    diff_threshold: float = 1.5

    skip_values: SkipValues = DEFAULT_SKIP_VALUES

    def _swap_random_blue_tiles(
        self,
        smaller: MiltyMapSlice,
        larger: MiltyMapSlice,
        qty_name: QtyName,
        rng: Random,
    ):
        """Swap random blue tiles between two slices, favorably for the quantity."""
        while True:
            # Select random tiles
            t_small = rng.choice(smaller.tiles)
            t_large = rng.choice(larger.tiles)
            # Skip red tiles (with 0 planets)... HACK: might not work for PoK
            if (len(t_small.planets) == 0) or (len(t_large.planets) == 0):
                continue
            # If they improve the metrics - swap them
            t_v_min = get_tile_quantity(t_small, qty_name)
            t_v_max = get_tile_quantity(t_large, qty_name)
            if t_v_min < t_v_max:
                logger.info("Swapping tiles...")
                # swap the tiles, then we will check again
                smaller.swap_tile(t_small, t_large)
                larger.swap_tile(t_large, t_small)
                break

    def _random_step(self, slices: list[MiltyMapSlice], rng: Random) -> bool:
        """Take a step towards fixing a random quantity.

        Returns True if something has changed.
        """
        thresh_map_raw: dict[QtyName, float | None] = {
            "total": self.min_value,
            "eff_resources": self.min_eff_resources,
            "eff_influence": self.min_eff_influence,
            "strict_resources": self.min_strict_resources,
            "strict_influence": self.min_strict_influence,
        }
        thresh_map: dict[QtyName, float] = {
            k: v for k, v in thresh_map_raw.items() if v is not None
        }
        to_fix: list[QtyName] = list(thresh_map)
        rng.shuffle(to_fix)
        for qty_name in to_fix:
            qty_name: QtyName = cast(QtyName, qty_name)
            sl_order = sorted(
                slices,
                key=lambda x: get_slice_quantity(
                    x, qty_name, skip_values=self.skip_values
                ),
            )
            threshold = thresh_map[qty_name]
            min_qty = get_slice_quantity(
                sl_order[0], qty_name, skip_values=self.skip_values
            )
            if min_qty < threshold:
                self._swap_random_blue_tiles(
                    smaller=sl_order[0],
                    larger=sl_order[-1],
                    qty_name=qty_name,
                    rng=rng,
                )
                return True  # we changed something
        return False

    def rebalance(
        self,
        original: MiltyDraftState,
        *,
        seed: Random | int | None = None,
        max_tries: int = 10,
    ) -> MiltyDraftState:
        """Try rebalancing the map."""
        # Set up stochastics
        if isinstance(seed, Random):
            # clone
            rng = Random()
            rng.setstate(seed.getstate())
        else:
            rng = Random(seed)

        # Make copy to avoid changing original data
        slices = [slc.model_copy(deep=True) for slc in original.slices]

        # Run steps
        for i_try in range(max_tries):
            logger.info(f"Rebalancing - step {i_try}")
            smth_changed = self._random_step(slices, rng)
            if not smth_changed:
                break  # nothing changed - we are stuck in our solution
        else:
            raise RuntimeError(f"Couldn't rebalance within {max_tries} tries.")

        # We're done before max_tries is reached
        logger.warning(f"Rebalancing took {i_try + 1} steps.")
        return MiltyDraftState(slices=slices, mecatol=original.mecatol)

    def make_generation(
        self,
        tileset: TileSet,
        *,
        seed: Random | int | None = None,
        n_slices: Literal[6] = 6,  # only 6 slices supported for now
        n_reds: Literal[2] = 2,  # 2 blue tiles
        n_blues: Literal[3] = 3,  # 3 blue tiles
        retries_global: int = 5,
        retries_gen: int = 5,
        retries_rebalance: int = 10,
    ) -> MiltyDraftState:
        """Generate a full draft set."""
        # Convert the seed to rng state
        if isinstance(seed, Random):
            # clone
            rng = Random()
            rng.setstate(seed.getstate())
        else:
            rng = Random(seed)

        # Generate
        for i_try_global in range(retries_global):
            try:
                raw_draft, rng = MiltyDraftState.make_random(
                    tileset=tileset,
                    seed=rng,
                    n_slices=n_slices,
                    n_reds=n_reds,
                    n_blues=n_blues,
                    retries=retries_gen,
                )
                # FIXME: is no state returned from here? We reuse the rng seeds...
                fixed_draft = self.rebalance(
                    raw_draft, seed=rng, max_tries=retries_rebalance
                )
                break
            except Exception:
                logger.exception(f"Failure in try {i_try_global}")
        else:
            raise RuntimeError(
                "Could not generate a draft set with retry settings: "
                f"{retries_global} global, {retries_gen} gen, "
                f"{retries_rebalance} rebalance."
            )
        return fixed_draft
