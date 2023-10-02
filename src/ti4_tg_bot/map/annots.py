"""Map annotations."""

from abc import abstractmethod
from pathlib import Path

from pydantic import BaseModel

from PIL.Image import Image
from PIL.Image import new as new_img
from PIL.ImageDraw import Draw
from PIL.ImageFont import truetype

from .hexes import HexCoord


class MapAnnotation(BaseModel):
    """Map annotation.

    Don't confuse with Python type annotations.
    """

    cell: HexCoord
    offset: tuple[float, float] = (0, 0)

    @abstractmethod
    def to_image(self) -> Image:
        """Convert to image."""

    def add_to_image(self, img: Image, center: tuple[float, float]) -> None:
        """Add self to image, with my center at given coordinates."""
        x_c, y_c = center[0] + self.offset[0], center[1] + self.offset[1]
        s_img = self.to_image()
        w, h = s_img.size
        x_left, y_top = int(x_c - w // 2), int(y_c - h // 2)
        img.paste(s_img, (x_left, y_top))


FONT_PATH = str(
    Path(__file__).parents[3] / "data" / "font" / "Handel-Gothic-D-Bold.otf"
)


class TextMapAnnotation(MapAnnotation):
    """Text-based map annotation."""

    text: str
    # Other options
    font_size: int = 50
    rect_radius: int = 5

    def to_image(self) -> Image:
        """Convert to image."""
        font_size = self.font_size
        rect_radius = self.rect_radius

        font = truetype(FONT_PATH, size=font_size)
        _, _, w_txt, h_txt = font.getbbox(self.text)  # left top corner
        w = w_txt + rect_radius * 2
        h = h_txt + rect_radius * 2
        img = new_img(
            "RGBA",
            size=(w, h),
            color=(255, 255, 255, 0),
        )
        d = Draw(img)
        d.rounded_rectangle(
            (0, 0, w, h),
            radius=5,
            outline=(0, 0, 0, 255),  # black outline
            fill=(255, 255, 255, 255),  # white fill
            width=3,
        )
        d.multiline_text(
            (rect_radius, rect_radius),
            self.text,
            font=font,
            fill=(0, 0, 0, 255),  # black stroke
            align="left",
        )
        return img
