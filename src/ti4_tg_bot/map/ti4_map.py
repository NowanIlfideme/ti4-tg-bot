"""TI Maps with placeholders."""

from pathlib import Path

from pydantic import BaseModel
from PIL.Image import Image
from PIL.Image import open as open_img

from ti4_tg_bot.data.models import Tile
from .annots import TextMapAnnotation
from .hexes import HexField
from .images import HexImageField


class PlaceholderTile(BaseModel):
    """Placeholder tile."""

    is_home: bool = False


MaybeTile = Tile | PlaceholderTile


class TIMaybeMap(HexField[MaybeTile]):
    """Map for TI4, including possible placeholder tiles."""

    scale: float = 450  # image scale for the tiles we have; later separate x and y
    annotations: list[TextMapAnnotation] = []

    def get_tile_image(self, base_path: Path, maybe_tile: MaybeTile) -> Image:
        """Get tile image based on tile or placeholder."""
        if isinstance(maybe_tile, Tile):
            num = maybe_tile.number
            return open_img(base_path / f"tile{num}.png")
        elif isinstance(maybe_tile, PlaceholderTile):
            if maybe_tile.is_home:
                return open_img(base_path / "tilehome.png")
            else:
                return open_img(base_path / "tilebw.png")
        raise TypeError(f"Unknown tile type passed: {maybe_tile!r}")

    def _tiles_to_image_field(self, base_path: Path) -> HexImageField:
        """Make image field from this map."""
        fld = {
            coord: self.get_tile_image(base_path, maybe_tile=maybe_tile)
            for (coord, maybe_tile) in self.cells.items()
        }
        return HexImageField(
            cells=fld,
            top_style=self.top_style,
            scale=self.scale,
            invert_y=self.invert_y,
            annotations=self.annotations,
        )

    def to_image(self, base_path: Path) -> Image:
        """Make singe image from this map."""
        # Get base image, which is the map itself
        tile_fld = self._tiles_to_image_field(base_path)
        # NOTE: Annotations are already added
        res_img = tile_fld.merge_to_image()
        return res_img
