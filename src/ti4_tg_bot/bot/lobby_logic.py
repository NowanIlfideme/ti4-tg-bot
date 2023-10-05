"""Logic for registering, entering and leaving lobbies."""

import asyncio
import tempfile
from pathlib import Path


from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.types import BotCommand, CallbackQuery, Message, User, Chat, FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.utils.media_group import MediaGroupBuilder

from ti4_tg_bot.map.gen_helper import MapGenHelper
from ti4_tg_bot.map.ti4_map import TIMaybeMap

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


class GameMaster(object):
    """Game master handler."""

    def __init__(self, last_msg: Message, users: dict[UserID, User]) -> None:
        # Stuff
        self.last_msg = last_msg
        self.users = dict(users)
        #
        self.mgh = MapGenHelper()

    @property
    def chat(self) -> Chat:
        return self.last_msg.chat

    def generate_map(self, map_name: str) -> tuple[TIMaybeMap, FSInputFile]:
        """Generate a map."""
        n_players = len(self.users)
        my_map, my_img = self.mgh.gen_random_map(
            n_players=n_players, map_title=map_name
        )
        tmpdir = tempfile.TemporaryDirectory().__enter__()  # yeah I know, sue me
        Path(tmpdir).mkdir(exist_ok=True, parents=True)
        file_name = f"{tmpdir}/{map_name}.jpg"
        my_img.convert("RGB").save(file_name)
        return my_map, FSInputFile(file_name)

    async def start_game(self, leader: User) -> None:
        """Start the game."""
        N_MAPS = 3
        POLL_ACTIVE_SEC = 60

        await self.last_msg.answer("Generating map...")
        map_pairs = [self.generate_map(f"map_{i+1}") for i in range(N_MAPS)]
        map_grp = MediaGroupBuilder(caption="Map Options")
        for mp, fsif in map_pairs:
            map_grp.add_photo(fsif)
        await self.last_msg.answer_media_group(media=map_grp.build())
        poll_msg = await self.last_msg.answer_poll(
            "Choose a map.",
            options=[f"Map {i+1}" for i in range(N_MAPS)],
            open_period=POLL_ACTIVE_SEC,
            is_anonymous=False,
        )
        await asyncio.sleep(POLL_ACTIVE_SEC)
        await poll_msg.answer("Let's pretend you chose the first one. ;)")

        chosen_map, chosen_map_img = map_pairs[0]
        self.last_msg = await self.last_msg.answer_photo(
            chosen_map_img, caption="You chose Map 1."
        )
        chosen_map

    async def add_choice(self):
        pass


class GlobalBackend(object):
    """Global backend."""

    def __init__(self):
        self.lobby_msg: dict[ChatID, Message] = {}
        self.lobby_users: dict[ChatID, dict[UserID, User]] = {}
        self.games: dict[ChatID, "GameMaster"] = {}

    # Lobby Stuff

    async def create_lobby(self, base_msg: Message):
        """Create a lobby based on a given message."""
        # Ensure we don't already have a lobby
        chat_id = base_msg.chat.id
        if chat_id in self.lobby_msg.keys():
            await base_msg.answer("Lobby already exists for this chat.")
            return
        elif chat_id in self.games.keys():
            await base_msg.answer("Can't create a lobby, game is in progress.")
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
            await msg.edit_text(f"Starting game with players: {user_str}")
            game = GameMaster(last_msg=msg, users=users)
            self.games[chat_id] = game
            del self.lobby_msg[chat_id]
            del self.lobby_users[chat_id]
            await game.start_game(leader=user)


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

    await gback.attempt_start_game(msg.chat.id, user=user)
