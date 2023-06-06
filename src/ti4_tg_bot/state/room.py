"""Model for rooms."""

from pydantic import BaseModel

ChatID = int
UserID = int


class Room(BaseModel):
    """A room, specified by a chat."""

    chat: ChatID
    users: list[UserID] = []


class GlobalState(BaseModel):
    """All rooms and such."""

    rooms: dict[ChatID, Room] = {}
