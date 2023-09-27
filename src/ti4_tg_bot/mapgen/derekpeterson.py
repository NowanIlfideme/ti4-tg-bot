"""Generate via derekpeterson's website.

https://ti4-map-generator.derekpeterson.ca/

Later I can just add the C++ code, call it locally, then read from the JSON.
But it was easier to scrape the site and offload stuff to keep this package pure Python.
"""

from typing import Annotated, Literal

import requests
import bs4
from io import BytesIO
from PIL import Image
from pydantic import BaseModel, Field, HttpUrl, validator


__all__ = ["MapGenerator", "MapGenRequest"]


_RACE_ORDER = [
    "The Federation of Sol",
    "The Mentak Coalition",
    "The Yin Brotherhood",  # "The Brotherhood of Yin",
    "The Embers of Muaat",
    "The Arborec",
    "The L1Z1X Mindnet",
    "The Winnu",
    "The Nekro Virus",
    "The Naalu Collective",
    "The Barony of Letnev",
    "The Clan of Saar",
    "The Universities of Jol-Nar",
    "Sardakk N'orr",
    "The Xxcha Kingdom",
    "The Yssaril Tribes",
    "The Emirates of Hacan",
    "The Ghosts of Creuss",
]


class MapGenRequest(BaseModel):
    """Map generation request."""

    class Config:
        validate_all = True

    n_players: Annotated[int, Field(ge=3, le=6)] = 6
    layout: str = "../res/layouts/standard_hex.json"  # FIXME uhh
    seed: int | None = None

    display_type: Literal[
        "tile_images_with_numbers", "tile_images_only", "numbers_only"
    ] = "tile_images_only"
    hires: bool = False
    race_selection_method: Literal["random", "chosen", "dummy_homes"] = "dummy_homes"
    races: list[int] | None = None
    star_by_star: bool = False
    pie_slice_assignment: Annotated[
        bool, Field(description="Assign value based on pie slices")
    ] = True
    # Special Params
    creuss_gets_wormhole: bool = True
    muaat_gets_supernova: bool = True
    saar_get_asteroids: bool = True
    winnu_clear_path_to_mecatol: bool = True
    include_all_wormholes: bool = True
    # Balancing parameters
    res_inf_weight: float | None = 1.0
    first_turn: float | None = 1.0
    resource_weight: float | None = 0.5
    influence_weight: float | None = 0.5
    tech_weight: float | None = 0.3
    trait_weight: float | None = 0.2
    ring_balance_weight: float | None = 1.0
    use_ring_balance: bool = False
    ring_balance: float | None = 1.0

    # TODO: Validators

    # Foo

    @validator("races", pre=True)
    def _foo(cls, v: list | None) -> list | None:
        if v is None:
            return None
        res: list[int] = []
        for xi in v:
            if isinstance(xi, int):
                res.append(xi)
            elif isinstance(xi, str):
                idx = _RACE_ORDER.index(xi)
                res.append(idx)
            else:
                raise ValueError(f"Unknown race: {xi}")
        return res

    @validator("races")
    def _chk_race_qty(cls, v: list | None, values: dict) -> list | None:
        rsm = values.get("race_selection_method", "dummy_homes")
        if v is None:
            if rsm == "chosen":
                raise ValueError("Chosen races, but unset!")
            return None
        elif rsm != "chosen":
            raise ValueError("Races not chosen, but set!")
        qty = values.get("n_players")
        if len(v) != qty:
            raise ValueError(f"Want {qty} players, but selected {len(v)} races: {v}")
        return v

    # Convert to request

    def as_request(self) -> dict:
        x_params = self.dict(exclude_none=True)
        for k, v in x_params.items():
            if v is False:
                x_params[k] = "false"
            elif v is True:
                x_params[k] = "true"
        if x_params["races"] is not None:
            x_params["races"] = " ".join([str(x + 1) for x in x_params["races"]])
        return x_params


class MapGenerator(BaseModel):
    """Map generator API."""

    base_url: HttpUrl = "https://ti4-map-generator.derekpeterson.ca"
    req_path: str = "/cgi-bin/ti4-map-generator-cgi.py"

    class Config:
        validate_all = True

    def gen_galaxy_image(self, req: MapGenRequest) -> Image:
        """Generate galaxy into an image."""
        gen_resp = requests.get(
            f"{self.base_url}{self.req_path}", params=req.as_request()
        )
        soup = bs4.BeautifulSoup(gen_resp.content, "html.parser")
        gal_path = soup.img.get("src")[1:]
        gal_resp = requests.get(f"{self.base_url}{gal_path}")
        img = Image.open(BytesIO(gal_resp.content))
        return img
