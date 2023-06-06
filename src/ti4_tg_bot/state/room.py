"""Model for rooms."""

from asyncio import Queue
from pydantic import BaseModel

ChatID = int
UserID = int


class Room(BaseModel):
    """A room, specified by a chat."""

    chat: ChatID
    users: list[UserID] = []


class GlobalState:
    """All rooms and such."""

    def __init__(
        self,
        rooms: dict[ChatID, Room] = {},
        queues: dict[UserID, Queue] = {},
    ):
        self.rooms = dict(rooms)
        self.queues = dict(queues)
