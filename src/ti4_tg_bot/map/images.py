"""Image tiling for hexes."""

from PIL.Image import Image
from PIL.Image import new as img_new


from .hexes import HexField


BBoxInt = tuple[int, int, int, int]
"""Bounding box: (left, upper, right, lower)."""


class HexImageField(HexField[Image]):
    """Field of images."""

    # make sure to scale properly...
    # FIXME: x and y scales might not be exactly correct in images...

    def merge_to_image(self) -> Image:
        """Merge all images to a single one."""
        # Ensure we have at least 1 image
        if len(self.cells) == 0:
            raise ValueError("No cells - can't make an image.")

        # Find bbox coordinates for every image
        imgs: list[Image] = []
        bboxes_i: list[BBoxInt] = []
        for (center_xi, center_yi), img_i in self.to_xy().items():
            imgs.append(img_i)
            wi, hi = img_i.size
            bbi = (
                center_xi - wi / 2,
                center_yi - hi / 2,
                center_xi + wi / 2,
                center_yi + hi / 2,
            )
            bboxes_i.append((int(bbi[0]), int(bbi[1]), int(bbi[2]), int(bbi[3])))
            # bboxes_i.append(tuple([round(p) for p in bbi]))  # less consistent

        # Calculate output bounding box and offsets
        min_x, min_y, max_x, max_y = bboxes_i[0]  # set at non-default ablues
        for left_i, upper_i, right_i, lower_i in bboxes_i:
            min_x = min(min_x, left_i)
            min_y = min(min_y, upper_i)
            max_x = max(max_x, right_i)
            max_y = max(max_y, lower_i)

        out_w: int = max_x - min_x
        out_h: int = max_y - min_y
        offset_x: int = -min_x
        offset_y: int = -min_y

        # Create image, then populate
        res = img_new(mode="RGBA", size=(out_w, out_h))
        for (left_i, upper_i, right_i, lower_i), img_i in zip(bboxes_i, imgs):
            new_bbox = (
                left_i + offset_x,
                upper_i + offset_y,
                right_i + offset_x,
                lower_i + offset_y,
            )
            res.paste(img_i, new_bbox, mask=img_i)

        return res
