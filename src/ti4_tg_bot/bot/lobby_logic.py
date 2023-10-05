"""Logic for registering, entering and leaving lobbies."""

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.types import BotCommand, CallbackQuery, Message, User
from aiogram.utils.keyboard import InlineKeyboardBuilder

cmds: dict[str, BotCommand] = {
    "start": BotCommand(command="start", description="Start using this bot."),
    "help": BotCommand(command="help", description="Get help for this bot."),
    # "status": BotCommand(command="status", description="Get current status (debug)."),
    # "create": BotCommand(command="create", description="Create a new lobby."),
    # "join": BotCommand(command="join", description="Join a lobby."),
    # "cancel": BotCommand(command="cancel", description="Cancel current lobby."),
    # "leave": BotCommand(command="leave", description="Leave the current lobby."),
}

r_lobby = Router()

ChatID = int
UserID = int


class LobbyStatusCallback(CallbackData, prefix="lobby_status"):
    """Lobby join or leave callback."""

    action: str


# Stupid global state, for now
lobby_msg: Message | None = None
lobby_users: dict[int, User] = {}


def make_joiner_kb() -> InlineKeyboardBuilder:
    """Make joiner keyboard."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Join", callback_data=LobbyStatusCallback(action="join").pack())
    builder.button(
        text="Leave", callback_data=LobbyStatusCallback(action="leave").pack()
    )
    builder.button(
        text="Start", callback_data=LobbyStatusCallback(action="start").pack()
    )
    return builder


class GlobalBackend(object):
    """Global backend."""

    def __init__(self):
        self.lobby_msg: dict[ChatID, Message] = {}
        self.lobby_users: dict[ChatID, dict[UserID, User]] = {}

    # Lobby Stuff

    async def create_lobby(self, base_msg: Message):
        """Create a lobby based on a given message."""
        # Ensure we don't already have a lobby
        chat_id = base_msg.chat.id
        if chat_id in self.lobby_msg:
            await base_msg.answer("Lobby already exists for this chat.")
            return

        # Create lobby data
        lobby_msg = await base_msg.answer(
            "Lobby created.", reply_markup=make_joiner_kb().as_markup()
        )
        self.lobby_msg[chat_id] = lobby_msg
        self.lobby_users[chat_id] = {}

        # Add creator
        await self.add_user_to_lobby(chat_id, base_msg.from_user)

    async def update_lobby(self, chat_id: ChatID):
        """Update the lobby, including message."""
        if chat_id not in self.lobby_msg:
            # raise ValueError(f"Bad chat ID: {chat_id}")
            # TODO: Log weirdness
            return

        msg = self.lobby_msg[chat_id]
        users = self.lobby_users[chat_id]
        if len(users) == 0:
            await msg.edit_text("Lobby is closed. /start to create a new one.")
            del self.lobby_msg[chat_id]
            del self.lobby_users[chat_id]
            return
        else:
            user_str = ", ".join(u.full_name for u in users.values())
            await msg.edit_text(
                f"In lobby: {user_str}", reply_markup=make_joiner_kb().as_markup()
            )

    async def add_user_to_lobby(self, chat_id: ChatID, user: User | None):
        """Add user to the lobby."""
        if user is None:
            # TODO: Log weirdness
            return
        self.lobby_users[chat_id][user.id] = user
        await self.update_lobby(chat_id)

    async def remove_user_from_lobby(self, chat_id: ChatID, user: User | None):
        """Remove user from the lobby."""
        if user is None:
            # TODO: log weirdness
            return
        if user.id in self.lobby_users[chat_id]:
            del self.lobby_users[chat_id][user.id]
        await self.update_lobby(chat_id)

    async def attempt_start_game(self, chat_id: ChatID, user: User | None):
        """Try to start the game."""
        if chat_id not in self.lobby_msg:
            # raise ValueError(f"Bad chat ID: {chat_id}")
            # TODO: Log weirdness
            return
        if user is None:
            # TODO: Log weirdness
            return
        msg = self.lobby_msg[chat_id]
        users = self.lobby_users[chat_id]
        if user.id not in users.keys():
            # TODO: lol, user isn't a player
            return
        user_str = ", ".join(u.full_name for u in users.values())
        if True:
            await msg.answer(f"Starting game with players: {user_str}")
            await msg.edit_text("Lobby is closed. /start to create a new one.")
            del self.lobby_msg[chat_id]
            del self.lobby_users[chat_id]

    # Game Stuff


gback = GlobalBackend()


@r_lobby.message(Command(cmds["help"]))
async def show_help(message: Message):
    """Show help."""


@r_lobby.message(CommandStart())
async def start_menu(message: Message, state: FSMContext):
    """Start."""
    await gback.create_lobby(message)


@r_lobby.callback_query(LobbyStatusCallback.filter(F.action == "join"))
async def cb_join(query: CallbackQuery, callback_data: LobbyStatusCallback):
    """Join callback."""
    #
    msg = query.message
    assert msg is not None
    user = query.from_user
    assert user is not None

    await gback.add_user_to_lobby(chat_id=msg.chat.id, user=user)


@r_lobby.callback_query(LobbyStatusCallback.filter(F.action == "leave"))
async def cb_leave(query: CallbackQuery, callback_data: LobbyStatusCallback):
    """Leave callback."""
    #
    msg = query.message
    assert msg is not None
    user = query.from_user
    assert user is not None

    await gback.remove_user_from_lobby(chat_id=msg.chat.id, user=user)


@r_lobby.callback_query(LobbyStatusCallback.filter(F.action == "start"))
async def cb_start(query: CallbackQuery, callback_data: LobbyStatusCallback):
    """Start callback."""
    #
    msg = query.message
    assert msg is not None
    user = query.from_user
    assert user is not None

    # TODO
    await gback.attempt_start_game(msg.chat.id, user=user)
