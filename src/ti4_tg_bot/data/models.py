"""Data models."""

from pydantic import BaseModel, HttpUrl


class Faction(BaseModel):
    """Faction information."""

    name: str
    wiki: HttpUrl


class GameInfo(BaseModel):
    """Game setup info."""

    factions: list[Faction]
    # TODO: tiles

    @property
    def faction_names(self) -> list[str]:
        """Faction names."""
        return [x.name for x in self.factions]
