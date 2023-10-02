"""Hexagonal map definition."""

from math import sqrt
from typing import Any, Generic, TypeVar, Literal

from typing_extensions import Annotated
from pydantic import BaseModel, RootModel, model_validator, Field, computed_field


class HexCoord(RootModel[tuple[int, int, int]]):
    """Hex coordinate definition, using cube coordinates.

    https://www.redblobgames.com/grids/hexagons/#coordinates
    """

    model_config = {"frozen": True}

    root: tuple[int, int, int]

    @property
    def q(self) -> int:
        """First 'q' coordinate."""
        return self.root[0]

    @property
    def r(self) -> int:
        """Second 'r' coordinate."""
        return self.root[1]

    @property
    def s(self) -> int:
        """Third 's' coordinate."""
        return self.root[2]

    @model_validator(mode="before")
    @classmethod
    def _set_third_coord(cls, data: Any) -> Any:
        """Set third coordinate if only given two."""
        if isinstance(data, (list, tuple)):
            if len(data) == 2:
                q, r = data
                return (q, r, -(q + r))
        return data

    @model_validator(mode="after")
    def _check_values(self) -> "HexCoord":
        """Check that coordinate values are okay."""
        q, r, s = self.q, self.r, self.s
        if q + r + s != 0:
            raise ValueError(f"Imbalanced hex coords: sum({q}, {r}, {s}) != 0")
        return self

    # Comparison operations

    def __eq__(self, rhs: "HexCoord") -> bool:
        if isinstance(rhs, HexCoord):
            return self.root == rhs.root
        return NotImplemented

    def __ne__(self, rhs: "HexCoord") -> bool:
        if isinstance(rhs, HexCoord):
            return self.root != rhs.root
        return NotImplemented

    # Vector operations

    def __add__(self, rhs: "HexCoord") -> "HexCoord":
        """Add this delta to a coordinate (or another delta)."""
        if isinstance(rhs, HexCoord):
            return HexCoord(root=(self.q + rhs.q, self.r + rhs.r, self.s + rhs.s))
        return NotImplemented

    def __sub__(self, rhs: "HexCoord") -> "HexCoord":
        """Add this delta to a coordinate (or another delta)."""
        if isinstance(rhs, HexCoord):
            return HexCoord(root=(self.q - rhs.q, self.r - rhs.r, self.s - rhs.s))
        return NotImplemented

    def __neg__(self) -> "HexCoord":
        """Coordinate negation."""
        return HexCoord(root=(-self.q, -self.r, -self.s))

    # Neighbors

    @property
    def neighbors(self) -> list["HexCoord"]:
        """Get direct neighbors of this cell.

        https://www.redblobgames.com/grids/hexagons/#neighbors
        """
        global HEX_UNIT_VECTORS
        return [self + vec for vec in HEX_UNIT_VECTORS]

    def get_neighborhood(self, distance: int = 1) -> list["HexCoord"]:
        """Get cells at most `distance` tiles away from self (including self)."""
        N = distance
        res: list[HexCoord] = []
        for q in range(-N, N + 1):
            for r in range(max(-N, -q - N), min(N, -q + N) + 1):
                s = -q - r
                res.append(HexCoord(root=(q, r, s)))
        return res

    @property
    def vector_length(self) -> int:
        """Length of the coord as a vector (i.e. distance from center).

        https://www.redblobgames.com/grids/hexagons/#distances
        """
        return max(abs(self.q), abs(self.r), abs(self.s))

    #

    @classmethod
    def nearest_hex(cls, qf: float, rf: float, sf: float) -> "HexCoord":
        """Nearest coordinates.

        https://www.redblobgames.com/grids/hexagons/#rounding
        """
        q = round(qf)
        r = round(rf)
        s = round(sf)

        qd = abs(q - qf)
        rd = abs(r - rf)
        sd = abs(s - sf)

        if (qd > rd) and (qd > sd):
            q = -(r + s)
        elif rd > sd:
            r = -(q + s)
        else:
            s = -(q + r)
        return cls(root=(q, r, s))


HEX_UNIT_VECTORS = tuple(
    HexCoord(root=_tup)
    for _tup in [(1, 0, -1), (1, -1, 0), (0, -1, 1), (-1, 0, 1), (-1, 1, 0), (0, 1, -1)]
)
"""Vector directions in 'cube' coordinates for hexes."""


ObjType = TypeVar("ObjType")

XYCoord = tuple[float, float]


class HexField(BaseModel, Generic[ObjType]):
    """Hexagonal field with objects that occupy some cells."""

    model_config = {"arbitrary_types_allowed": True}  # so that ObjType can be any

    cells: dict[HexCoord, ObjType] = {}

    # Styles for conversion to pixel coords
    top_style: Literal["flat", "pointy"] = "flat"
    scale: Annotated[float, Field(description="Size of a hexagon side.")] = 1.0
    invert_y: bool = True

    @computed_field
    @property
    def basis_qr_to_xy(self) -> tuple[tuple[float, float], tuple[float, float]]:
        """Matrix convertin QR to XY coords."""
        # Basis vectors of 'q' and 'r' to 'xy' coords.
        y_sign = -1 if self.invert_y else 1
        if self.top_style == "flat":
            (qx, qy) = (1.5, sqrt(3) / 2 * y_sign)
            (rx, ry) = (0, sqrt(3) * y_sign)
        else:  # pointy
            (qx, qy) = (sqrt(3), 0 * y_sign)
            (rx, ry) = (sqrt(3) / 2, 1.5 * y_sign)
        return ((qx, qy), (rx, ry))

    def cell_to_xy(self, hexcoord: HexCoord) -> XYCoord:
        """Convert a hex coord to XY coordinates."""
        ((qx, qy), (rx, ry)) = self.basis_qr_to_xy

        qi = hexcoord.q
        ri = hexcoord.r
        xi = (qi * qx + ri * rx) * self.scale
        yi = (qi * qy + ri * ry) * self.scale
        return xi, yi

    def to_xy(self) -> dict[XYCoord, ObjType]:
        """Convert cells to XY coordinates (of their centers).

        https://www.redblobgames.com/grids/hexagons/#hex-to-pixel
        """
        # Convert coordinates
        res: dict[XYCoord, ObjType] = {}
        for hexcoord, obj in self.cells.items():
            xi, yi = self.cell_to_xy(hexcoord)
            res[(xi, yi)] = obj
        return res

    @classmethod
    def from_xy_map(
        cls,
        point_to_obj: dict[XYCoord, ObjType],
        *,
        top_style: Literal["flat", "pointy"] = "flat",
        scale: float = 1.0,
        invert_y: bool = True,
    ) -> "HexField[ObjType]":
        """Get field from an XY coordinate map.

        Converts XY coordinates to their nearest cells.

        https://www.redblobgames.com/grids/hexagons/#pixel-to-hex
        """

        # Basis vectors of 'x' and 'y' to 'qr' coords.
        y_sign = -1 if invert_y else 1
        if top_style == "flat":
            (xq, yq) = (2.0 / 3, 0 * y_sign)
            (xr, yr) = (-1.0 / 3, sqrt(3) / 3 * y_sign)
        elif top_style == "pointy":  # pointy
            (xq, yq) = (sqrt(3) / 3, -1.0 / 3 * y_sign)
            (xr, yr) = (0, 2.0 / 3 * y_sign)
        else:
            raise ValueError(f"Unknown top_style {top_style!r}")

        # Convert coordinates and map raw coords
        raw_map: dict[tuple[float, float, float], ObjType] = {}
        for (xi, yi), obj in point_to_obj.items():
            qi = (xi * xq + yi * yq) / scale
            ri = (xi * xr + yi * yr) / scale
            raw_map[qi, ri, -(qi + ri)] = obj

        # Map to nearest hex coords
        res_map: dict[HexCoord, ObjType] = {
            HexCoord.nearest_hex(*qrs): obj for (qrs, obj) in raw_map.items()
        }

        # Set all options
        res = HexField[ObjType](
            cells=res_map,
            top_style=top_style,
            scale=scale,
            invert_y=invert_y,
        )
        return res
