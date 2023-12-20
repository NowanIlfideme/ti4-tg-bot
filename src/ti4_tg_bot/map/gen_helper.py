"""Helper for generating things."""

import logging
import re
from pathlib import Path
from random import shuffle

from PIL.Image import Image
from pydantic import BaseModel
from pydantic_yaml import parse_yaml_file_as

from ti4_tg_bot.data import base_game
from ti4_tg_bot.data.models import GameInfo
from ti4_tg_bot.map.annots import TextMapAnnotation
from ti4_tg_bot.map.hexes import HexCoord, get_spiral
from ti4_tg_bot.map.ti4_layout import TILayout, YamlTILayout
from ti4_tg_bot.map.ti4_map import TIMaybeMap, PlaceholderTile

logger = logging.getLogger(__name__)

PATH_IMGS = Path(__file__).resolve().parents[3] / "data/tiles"
PATH_LAYOUTS = Path(__file__).resolve().parents[3] / "data/layouts"

MAP_STRING_REGEX = r"^\d{1,2}(?:\s\d{1,2}){35}$"


class MapGenHelper(BaseModel):
    """Map generation helper object."""

    path_imgs: Path = PATH_IMGS
    path_layouts: Path = PATH_LAYOUTS
    game_info: GameInfo = base_game

    def load_available_layouts(self) -> list[TILayout]:
        """Load all available layouts."""
        res: list[TILayout] = []
        for yml_path in list(self.path_layouts.rglob("*.yaml")):
            try:
                layout_i = parse_yaml_file_as(YamlTILayout, yml_path).fix_layout()
                res.append(layout_i)
            except Exception:
                logger.warning(f"Failed to load file as layout: {yml_path!s}")
        return res

    def load_layout(self, name: str) -> TILayout:
        """Load a layout with a given name."""
        raw = parse_yaml_file_as(YamlTILayout, self.path_layouts / f"{name}.yaml")
        layout: TILayout = raw.fix_layout()
        return layout

    def import_map(
        self,
        n_players: int,
        map_string: str,
        coord_anns: bool = False,
        map_title: str | None = None,
    ) -> tuple[TIMaybeMap, Image]:
        """Import a map from the given map string."""
        if not re.match(MAP_STRING_REGEX, map_string):
            raise ValueError("Bad map string.")

        # Get spiral coord
        tile_nums = [18] + [int(x) for x in map_string.split()]
        coord_to_num: dict[HexCoord, int] = {}
        for coord, tn in zip(get_spiral(), tile_nums):
            coord_to_num[coord] = tn

        # Convert to
        cells = {}
        annots: list[TextMapAnnotation] = []
        home_num = 0
        home_tiles = ["A", "B", "C", "D", "E", "F"]
        for coord, num in coord_to_num.items():
            if num == 0:
                home_name = home_tiles[home_num]
                tile_i = PlaceholderTile(home_name=home_name)
                home_num += 1
                annots.append(
                    TextMapAnnotation(
                        cell=coord,
                        text=home_name,
                        offset=(-150, 0),
                        font_size=80,
                    )
                )
            else:
                tile_i = self.game_info.tiles.get_by_number(num)
            cells[coord] = tile_i

        final_map = TIMaybeMap(cells=cells, annotations=annots)

        # Make image
        img = final_map.to_image(base_path=self.path_imgs)
        return final_map, img

    def gen_random_map(
        self,
        n_players: int,
        layout: TILayout | None = None,
        coord_anns: bool = False,
        map_title: str | None = None,
    ) -> tuple[TIMaybeMap, Image]:
        """Generate a completely random map."""
        # Set the layout
        if layout is None:
            lts = self.load_available_layouts()
            avail = [lyo for lyo in lts if lyo.players == n_players]
            if len(avail) == 0:
                raise ValueError(f"No layouts exist for {n_players} players.")
            layout = avail[0]  # lol yes first one

        # Create random tile map (yes, this is illegal)
        rand_tiles = self.game_info.tiles.blue_tiles + self.game_info.tiles.red_tiles
        shuffle(rand_tiles)
        random_map = layout.to_maybe_map(self.game_info)
        for i, coord in enumerate(layout.free_tiles):
            random_map.cells[coord] = rand_tiles[i]

        # Add annotations
        anns: list[TextMapAnnotation] = []
        # Coordinate annotations?
        if coord_anns:
            for cell in random_map.cells.keys():
                anns.append(
                    TextMapAnnotation(
                        cell=cell,
                        text=f"({cell.q}, {cell.r}, {cell.s})",
                        font_size=60,
                        offset=(0, 200),
                    )
                )
        # Map Name?
        if map_title is not None:
            anns.append(
                TextMapAnnotation(
                    cell=(0, 0, 0),  # type: ignore
                    text=map_title,
                    font_size=120,
                    offset=(0, -200),
                )
            )

        random_map.annotations = anns + random_map.annotations

        # Make image
        img = random_map.to_image(base_path=self.path_imgs)
        return random_map, img

    # def gen_milty_base(
    #     self,
    #     n_players: int,
    #     layout: TILayout | None = None,
    #     coord_anns: bool = False,
    #     map_title: str | None = None,
    # ) -> tuple[TIMaybeMap, Image]:
    #     """Generate a completely random map."""
