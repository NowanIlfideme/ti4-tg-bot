"""Logic for registering, entering and leaving lobbies."""

import asyncio
import tempfile
import logging
from pathlib import Path
from random import Random
from datetime import datetime
from io import BytesIO
import re

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BotCommand,
    BufferedInputFile,
    CallbackQuery,
    Message,
    User,
    Chat,
    FSInputFile,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.utils.media_group import MediaGroupBuilder

from ti4_tg_bot.data.models import Faction
from ti4_tg_bot.map.annots import TextMapAnnotation
from ti4_tg_bot.map.gen_helper import MapGenHelper
from ti4_tg_bot.map.milty import SliceRebalancer
from ti4_tg_bot.map.ti4_map import TIMaybeMap, PlaceholderTile

logger = logging.getLogger(__name__)

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

MAP_STRING_REGEX = r"^\d{1,2}(?:\s\d{1,2}){35}$"


def user_att(user: User) -> str:
    """Try to 'at' the user."""
    if user.username is not None:
        att = "@" + user.username
    else:
        att = user.full_name
    return att


class LobbyStatusCallback(CallbackData, prefix="lobby_status"):
    """Lobby action callback."""

    action: str


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


class UserChoiceCallback(CallbackData, prefix="user_choice"):
    """Lobby join or leave callback."""

    chat_id: ChatID
    user_id: UserID
    label: str
    num: int


def make_choices_kb(
    chat_id: ChatID,
    user_id: UserID,
    choices: list[str],
    *,
    max_width: int | None = None,
) -> InlineKeyboardBuilder:
    """Make choices keyboard."""
    builder = InlineKeyboardBuilder()
    for i, choice in enumerate(choices):
        builder.button(
            text=choice,
            callback_data=UserChoiceCallback(
                chat_id=chat_id, user_id=user_id, label=choice, num=i
            ).pack(),
        )
    if max_width is not None:
        builder.adjust(max_width)
    return builder


class GameCurrState(object):
    """Game state handler."""

    def __init__(self, last_msg: Message, users: dict[UserID, User]) -> None:
        # Stuff
        self.last_msg = last_msg
        self.users = dict(users)
        #
        self.mgh = MapGenHelper()
        self.queues: dict[UserID, asyncio.Queue[str]] = {}
        # State
        self.locations: dict[UserID, str] = {}
        self.factions: dict[UserID, Faction] = {}

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
        w, h = my_img.size
        my_img.convert("RGB").resize((w // 2, h // 2)).save(file_name)
        return my_map, FSInputFile(file_name)

    def map_from_string(self, map_str: str) -> tuple[TIMaybeMap, FSInputFile]:
        """Make a map from a map string."""
        map_name = "imported_map"
        n_players = len(self.users)
        my_map, my_img = self.mgh.import_map(
            n_players=n_players, map_string=map_str, map_title="Imported Map"
        )

        tmpdir = tempfile.TemporaryDirectory().__enter__()  # yeah I know, sue me
        Path(tmpdir).mkdir(exist_ok=True, parents=True)
        file_name = f"{tmpdir}/{map_name}.jpg"
        w, h = my_img.size
        my_img.convert("RGB").resize((w // 2, h // 2)).save(file_name)
        return my_map, FSInputFile(file_name)

    async def request_choice(
        self,
        user: UserID | User,
        prompt: str,
        choices: list[str],
        *,
        max_width: int | None = None,
    ) -> str:
        """Helper to request a choice of a user."""
        if isinstance(user, User):
            user_id = user.id
        else:
            user_id = user

        if user_id not in self.users.keys():
            raise ValueError("Bad user ID given.")
        user = self.users[user_id]

        chat_id = self.last_msg.chat.id
        kb = make_choices_kb(
            chat_id=chat_id,
            user_id=user_id,
            choices=choices,
            max_width=max_width,
        ).as_markup()
        qq = asyncio.Queue[str]()
        self.queues[user_id] = qq

        at_prompt = f"{user_att(user)}: {prompt}"
        req_msg = await self.last_msg.answer(at_prompt, reply_markup=kb)
        res = await qq.get()
        await req_msg.edit_text(f"{user.full_name}: {prompt}\nChosen: {res}")
        return res

    async def request_map_string(
        self,
        user: UserID | User,
        prompt: str,
    ) -> str:
        """Request a map string."""
        if isinstance(user, User):
            user_id = user.id
        else:
            user_id = user
        if user_id not in self.users.keys():
            raise ValueError("Bad user ID given.")
        user = self.users[user_id]

        qq = asyncio.Queue[str]()
        self.queues[user_id] = qq

        at_prompt = f"{user_att(user)}: {prompt}"
        await self.last_msg.answer(at_prompt)
        res = await qq.get()
        return res


FLOW_MSG = "\n".join(
    [
        "Please choose a game setup flow:",
        "A) Gen 3 maps, choose map, choose place, ban faction, pick faction.",
        "B) Enter map string, choose map, choose place, ban faction, pick faction.",
        "C) ",
    ]
)


class GlobalBackend(object):
    """Global backend."""

    def __init__(self):
        self.lobby_msg: dict[ChatID, Message] = {}
        self.lobby_users: dict[ChatID, dict[UserID, User]] = {}
        self.games: dict[ChatID, "GameCurrState"] = {}

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
            game = GameCurrState(last_msg=msg, users=users)
            self.games[chat_id] = game
            del self.lobby_msg[chat_id]
            del self.lobby_users[chat_id]
            # await game.start_game(leader=user)

            # TEST choice

            choice = await game.request_choice(user, FLOW_MSG, ["A", "B", "C"])
            if choice == "A":
                await self.game_flow_a(chat_id=chat_id, leader=user)
            elif choice == "B":
                await self.game_flow_b(chat_id=chat_id, leader=user)
            elif choice == "C":
                await self.game_flow_c(chat_id=chat_id, leader=user)
            else:
                await msg.answer("Unknown choice - ignoring.")

            await msg.answer("Game setup is done, you may /start a new lobby.")
            del self.games[chat_id]

    async def game_flow_a(self, chat_id: ChatID, leader: User):
        """Game flow A."""
        game = self.games[chat_id]
        msg = game.last_msg

        # Generate and choose map...
        N_MAPS = 3
        await game.last_msg.answer("Generating map...")
        map_pairs = [game.generate_map(f"map_{i+1}") for i in range(N_MAPS)]
        map_grp = MediaGroupBuilder(caption="Map Options")
        for mp, fsif in map_pairs:
            map_grp.add_photo(fsif)
        await msg.answer_media_group(media=map_grp.build())
        await msg.answer_poll(
            "Choose a map.",
            options=[f"Map {i+1}" for i in range(N_MAPS)],
            is_anonymous=False,
        )
        sel_map_name = await game.request_choice(
            leader,
            "Which map was selected in the poll?",
            [f"Map {i+1}" for i in range(N_MAPS)],
        )
        sel_map: int = int(sel_map_name[4:]) - 1

        chosen_map, chosen_map_img = map_pairs[sel_map]
        msg = await msg.answer_photo(
            chosen_map_img, caption=f"Playing on {sel_map_name}."
        )

        # Create random order
        # Set seed and RNG
        seed = int(datetime.utcnow().timestamp() * 1000)
        rng = Random(seed)
        logger.info(f"Using seed: {seed}")
        # await msg.answer_dice()

        # Create order
        n_players = len(game.users)
        user_order = rng.sample(list(game.users.values()), k=n_players)
        await msg.answer(
            "\n".join(
                ["Player order:"]
                + [f"{i+1}. {user_att(u)}" for i, u in enumerate(user_order)]
            )
        )

        # CHOOSE location
        possible_locations = list("ABCDEF")[:n_players]
        await msg.answer(f"Selecting location in reverse order ({n_players} -> 1).")
        for user in reversed(user_order):
            sel_loc = await game.request_choice(
                user,
                "Choose your map location:",
                choices=possible_locations,
            )
            game.locations[user.id] = sel_loc
            possible_locations.remove(sel_loc)

        available_factions = {fn.name: fn for fn in game.mgh.game_info.factions}

        # BAN factions
        await msg.answer(f"Banning factions in forward order (1 -> {n_players})")
        for user in user_order:
            ban_fac = await game.request_choice(
                user,
                "Choose a faction to ban:",
                choices=list(available_factions),
                max_width=2,
            )
            del available_factions[ban_fac]

        # PICK factions
        await msg.answer(f"Picking factions in reverse order ({n_players} -> 1)")
        for user in user_order:
            sel_fac = await game.request_choice(
                user,
                "Choose a faction to play:",
                choices=list(available_factions),
                max_width=2,
            )
            sel_fac_info = available_factions[sel_fac]
            game.factions[user.id] = sel_fac_info
            del available_factions[sel_fac]

        # RESULTS
        home_coords = {
            v.home_name: c
            for c, v in chosen_map.cells.items()
            if (isinstance(v, PlaceholderTile) and v.home_name is not None)
        }
        fac_to_tile = {tile.race: tile for tile in game.mgh.game_info.tiles.home_tiles}

        lines = ["Final Game Setup"]
        for i, user in enumerate(user_order):
            loc = game.locations[user.id]
            fac = game.factions[user.id]

            home_coord = home_coords[loc]
            home_tile = fac_to_tile[fac.name]
            # Replce home tile and add annotation
            chosen_map.cells[home_coord] = home_tile
            chosen_map.annotations.append(  # TODO - consider replacing annotation?...
                TextMapAnnotation(
                    cell=home_coord,
                    offset=(0, -120),
                    text=user_att(user),
                    font_size=80,
                )
            )
            # Add info
            fac_o = f'<a href="{fac.wiki}">{fac.name}</a>'
            lines.append(f"{i+1}. {user_att(user)} at {loc} playing as <b>{fac_o}</b>")
        lines.append("Have fun! Use /start to create a new lobby, if necessary.")
        # Save map file
        tmpdir = tempfile.TemporaryDirectory().__enter__()  # yeah I know, sue me
        Path(tmpdir).mkdir(exist_ok=True, parents=True)
        file_name = f"{tmpdir}/{chat_id}.jpg"
        chosen_map_img = chosen_map.to_image(game.mgh.path_imgs)
        chosen_map_img.convert("RGB").save(file_name)
        img = FSInputFile(file_name)
        # Upload and add caption
        await msg.answer_photo(photo=img, caption="\n".join(lines))

    async def game_flow_b(self, chat_id: ChatID, leader: User):
        """Game flow B."""
        game = self.games[chat_id]
        msg = game.last_msg

        # Generate and choose map...
        map_str = await game.request_map_string(
            leader, prompt="Please enter a map string with `/mapstr 12 ... 34`"
        )
        chosen_map, chosen_map_img = game.map_from_string(map_str)
        msg = await msg.answer_photo(chosen_map_img, caption="Playing on imported map.")

        # Create random order
        # Set seed and RNG
        seed = int(datetime.utcnow().timestamp() * 1000)
        rng = Random(seed)
        logger.info(f"Using seed: {seed}")
        # await msg.answer_dice()

        # Create order
        n_players = len(game.users)
        user_order = rng.sample(list(game.users.values()), k=n_players)
        await msg.answer(
            "\n".join(
                ["Player order:"]
                + [f"{i+1}. {user_att(u)}" for i, u in enumerate(user_order)]
            )
        )

        # CHOOSE location
        possible_locations = list("ABCDEF")[:n_players]
        await msg.answer(f"Selecting location in reverse order ({n_players} -> 1).")
        for user in reversed(user_order):
            sel_loc = await game.request_choice(
                user,
                "Choose your map location:",
                choices=possible_locations,
            )
            game.locations[user.id] = sel_loc
            possible_locations.remove(sel_loc)

        available_factions = {fn.name: fn for fn in game.mgh.game_info.factions}

        # BAN factions
        await msg.answer(f"Banning factions in forward order (1 -> {n_players})")
        for user in user_order:
            ban_fac = await game.request_choice(
                user,
                "Choose a faction to ban:",
                choices=list(available_factions),
                max_width=2,
            )
            del available_factions[ban_fac]

        # PICK factions
        await msg.answer(f"Picking factions in reverse order ({n_players} -> 1)")
        for user in reversed(user_order):
            sel_fac = await game.request_choice(
                user,
                "Choose a faction to play:",
                choices=list(available_factions),
                max_width=2,
            )
            sel_fac_info = available_factions[sel_fac]
            game.factions[user.id] = sel_fac_info
            del available_factions[sel_fac]

        # RESULTS
        home_coords = {
            v.home_name: c
            for c, v in chosen_map.cells.items()
            if (isinstance(v, PlaceholderTile) and v.home_name is not None)
        }
        fac_to_tile = {tile.race: tile for tile in game.mgh.game_info.tiles.home_tiles}

        lines = ["Final Game Setup"]
        for i, user in enumerate(user_order):
            loc = game.locations[user.id]
            fac = game.factions[user.id]

            home_coord = home_coords[loc]
            home_tile = fac_to_tile[fac.name]
            # Replce home tile and add annotation
            chosen_map.cells[home_coord] = home_tile
            chosen_map.annotations.append(  # TODO - consider replacing annotation?...
                TextMapAnnotation(
                    cell=home_coord,
                    offset=(0, -120),
                    text=user_att(user),
                    font_size=80,
                )
            )
            # Add info
            fac_o = f'<a href="{fac.wiki}">{fac.name}</a>'
            lines.append(f"{i+1}. {user_att(user)} at {loc} playing as <b>{fac_o}</b>")
        lines.append("Have fun! Use /start to create a new lobby, if necessary.")
        # Save map file
        tmpdir = tempfile.TemporaryDirectory().__enter__()  # yeah I know, sue me
        Path(tmpdir).mkdir(exist_ok=True, parents=True)
        file_name = f"{tmpdir}/{chat_id}.jpg"
        chosen_map_img = chosen_map.to_image(game.mgh.path_imgs)
        w, h = chosen_map_img.size
        chosen_map_img.convert("RGB").resize((w // 2, h // 2)).save(file_name)
        img = FSInputFile(file_name)
        # Upload and add caption
        await msg.answer_photo(photo=img, caption="\n".join(lines))

    async def game_flow_c(self, chat_id: ChatID, leader: User):
        """Game flow C."""
        game = self.games[chat_id]
        msg = game.last_msg

        # Prepare map generator
        gen = game.mgh
        tileset = gen.game_info.tiles

        # Select how many factions to add
        opts_n_factions = range(6, len(gen.game_info.factions) // 2 + 1)
        choice_raw_n_factions = await game.request_choice(
            leader, "How many factions to add?", [str(x) for x in opts_n_factions]
        )
        choice_n_factions = int(choice_raw_n_factions)

        # Create random order
        # Set seed and RNG
        seed = int(datetime.utcnow().timestamp() * 1000)
        rng = Random(seed)
        map_seed = rng.randint(1, 123456789)
        logger.info(f"Main seed: {seed}")
        logger.info(f"Map seed: {map_seed}")
        # await msg.answer_dice()

        # Create order
        n_players = len(game.users)
        user_order = rng.sample(list(game.users.values()), k=n_players)

        # Create draft state
        sr = SliceRebalancer(
            min_value=9,
            min_strict_resources=4,
            min_eff_resources=1,
            min_strict_influence=4,
            min_eff_influence=1,
        )
        logger.info("Generating draft state...")
        draft_state = gen.gen_milty_base(
            n_factions=choice_n_factions,
            slice_rebalancer=sr,
            seed=map_seed,
        )

        # Talk to players
        lines = (
            ["Player order:"]
            + [f"{i+1}. {user_att(u)}" for i, u in enumerate(user_order)]
            + ["Factions:"]
            + [fac_i.name for fac_i in draft_state.factions]
        )

        # Build media group
        media_group = MediaGroupBuilder(caption="\n".join(lines))

        # Prepare initial map
        current_map, map_img = gen.milty_to_image(draft_state, map_title="Current Map")
        w, h = map_img.size
        DOWNSCALE_FACTOR = 2
        tmpio = BytesIO()
        map_img.convert("RGB").resize(
            (w // DOWNSCALE_FACTOR, h // DOWNSCALE_FACTOR)
        ).save(tmpio, format="PNG")
        media_group.add_photo(
            BufferedInputFile(tmpio.getvalue(), filename=f"{chat_id}/initial_map.png")
        )

        # Prepare images of slices
        slice_imgs = draft_state.visualize_slices(gen.path_imgs)
        slice_img_files: list[BufferedInputFile] = []
        for i, si in enumerate(slice_imgs):
            tmpio = BytesIO()
            si.save(tmpio, format="PNG")
            fi = BufferedInputFile(
                tmpio.getvalue(), filename=f"{chat_id}/slice_{i}.png"
            )
            slice_img_files.append(fi)  # not needed?

            media_group.add_photo(fi)
        # Ok, send the message
        final_msgs = await msg.answer_media_group(media=media_group.build())
        raw_photo_ids: list[str] = []
        for msg_i in final_msgs:
            if msg_i.photo is not None:
                raw_photo_ids.append(msg_i.photo[2].file_id)  # lol


gback = GlobalBackend()


@r_lobby.message(Command(cmds["help"]))
async def show_help(message: Message):
    """Show help."""
    await message.answer("Use /start to start the game in this chat.")


@r_lobby.message(Command("mapstr"))
async def set_map_string(message: Message):
    """Set map string."""
    user = message.from_user
    if user is None:
        return
    if message.text is None:
        return
    game = gback.games.get(message.chat.id)
    if game is None:
        return
    qq = game.queues.get(user.id)
    if qq is None:
        return
    map_str = message.text.lstrip("/mapstr ").strip()
    if re.match(MAP_STRING_REGEX, map_str):
        await message.answer("Map string accepted.")
        await qq.put(map_str)
    else:
        await message.answer("Improper map string, ignoring.")


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


@r_lobby.callback_query(UserChoiceCallback.filter())
async def cb_choice(query: CallbackQuery, callback_data: UserChoiceCallback):
    """User selected something callback."""
    #
    msg = query.message
    assert msg is not None
    user = query.from_user
    assert user is not None

    chat_id = msg.chat.id
    game_state = gback.games.get(chat_id)
    if game_state is None:
        return
    if callback_data.user_id != user.id:
        logger.info("Someone pressed another person's button! Oh no you didn't!")
        return
    qq = game_state.queues.get(user.id)
    if qq is None:
        logger.warning(f"Queue for user {user.full_name} didn't exist.")
        return
    await qq.put(callback_data.label)
