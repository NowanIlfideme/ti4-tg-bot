"""Main logic."""

from datetime import datetime
from random import Random

from aiogram import Router
from aiogram.enums import ChatType
from aiogram.filters import Command, Filter
from aiogram.types import Message


from ti4_tg_bot.state.room import GlobalState, Room

state = GlobalState()
router = Router()


MIN_PLAYERS = 1
MAX_PLAYERS = 6


class GroupOnly(Filter):
    """Only allow commands in groups."""

    async def __call__(self, message: Message) -> bool:
        if not isinstance(message, Message):
            return False
        return message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]


class InLobby(Filter):
    """Only allow command in active lobby."""

    def __init__(self, state: GlobalState) -> None:
        super().__init__()
        self.state = state

    async def __call__(self, message: Message) -> bool:
        if not isinstance(message, Message):
            return False
        chat_id = message.chat.id

        res = chat_id in state.rooms
        if not res:
            await message.answer("There is no active game. /start to create a new one.")
        return res


async def show_status(message: Message) -> None:
    """Show current status of the lobby."""
    chat_id = message.chat.id

    if chat_id not in state.rooms:
        await message.answer("There is no active game. /start to create a new one.")
        return

    room = state.rooms[chat_id]
    members = [await message.chat.get_member(x) for x in room.users]
    member_names = [f"@{x.user.username}" for x in members]
    await message.answer("Current players: " + ", ".join(member_names))


@router.message(Command("start"), GroupOnly())
async def cmd_start(message: Message) -> None:
    """Start a new game."""
    chat_id = message.chat.id
    uid = message.from_user.id

    # Check for existing game
    if chat_id in state.rooms:
        await message.answer("Game already started. You may /cancel to restart.")
        return

    # Start the game
    state.rooms[chat_id] = Room(chat=chat_id, users=[uid])

    # Reply to the chat.
    reply = (
        f"<b>{message.from_user.full_name}</b> is starting a new game!"
        + "\nYou can /join or /leave the lobby."
        + "\nYou can also /cancel the game."
        + "\nOnce everyone has joined, /create the game."
    )
    await message.answer(reply)
    await show_status(message)


@router.message
@router.message(Command("start"))
async def cmd_bad_start(message: Message) -> None:
    """Can'."""
    await message.answer("This bot can only be used in a group.")


@router.message(Command("cancel"), GroupOnly())
async def cmd_cancel(message: Message) -> None:
    """Cancel the current game."""
    chat_id = message.chat.id

    # Check for existing game
    if chat_id in state.rooms:
        del state.rooms[chat_id]
        await message.answer("Canceled game. /start to create a new one.")
    else:
        await message.answer("There is no active game.")


@router.message(Command("join"), GroupOnly(), InLobby(state))
async def cmd_join(message: Message) -> None:
    """Join the current game."""
    chat_id = message.chat.id
    uid = message.from_user.id

    room = state.rooms[chat_id]
    if uid not in room.users:
        room.users.append(uid)

    await show_status(message)


@router.message(Command("leave"), GroupOnly(), InLobby(state))
async def cmd_leave(message: Message) -> None:
    """Leave the current game."""
    chat_id = message.chat.id
    uid = message.from_user.id

    room = state.rooms[chat_id]
    if uid in room.users:
        room.users.remove(uid)

    await show_status(message)


@router.message(Command("create"), GroupOnly(), InLobby(state))
async def cmd_create(message: Message) -> None:
    """Create a game setup."""
    chat_id = message.chat.id
    uid = message.from_user.id  # noqa
    room = state.rooms[chat_id]
    if len(room.users) < MIN_PLAYERS:
        await message.answer(f"Need at least {MIN_PLAYERS} players; some should /join")
        return
    elif len(room.users) > MAX_PLAYERS:
        await message.answer(f"Need at most {MAX_PLAYERS} players; some should /leave")
        return

    # Set seed and RNG
    seed = int(datetime.utcnow().timestamp() * 1000)
    rng = Random(seed)
    await message.answer(f"Using seed: {seed}")
    await message.answer_dice()

    # Create order
    order = rng.sample(room.users, k=len(room.users))
    order_mems = [await message.chat.get_member(x) for x in order]
    order_names = [f"@{x.user.username}" for x in order_mems]
    await message.answer(
        "Choosing Order:\n"
        + "\n".join([f"{i+1}. {nm}" for i, nm in enumerate(order_names)])
    )

    # Select races
    # TODO

    # Close game game
    del state.rooms[chat_id]
    await message.answer("Finished game setup. Have fun!\n/start to create a new one.")
