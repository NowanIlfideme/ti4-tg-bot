"""Main logic."""

from datetime import datetime
from random import Random

import asyncio
from aiogram import Bot, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, Filter
from aiogram.types import Message, User, BotCommand
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

from ti4_tg_bot.data import base_game
from ti4_tg_bot.state.room import GlobalState, Room, UserID

state = GlobalState()
router = Router()

BOTNAME = "TwilightGenBot"
CLEANUP_KEYBOARD = True
USE_LOCATION = False
HELP_STR = f"""Hello! I help set up games of Twilight Imperium: 4th Edition. \
Right now, I can only help with picking factions from the base game.

In order to start, create a group chat and add me: @{BOTNAME}
Please tell everyone to add me (click on me and /start the private conversation). \
Otherwise, I'll be unable to message them, and we'll be waiting a long time...

In your group chat, you can /start the lobby.
Everyone who wants to play should /join the lobby.
Once everyone joined, choose one of the "create_*" commands to start faction selection.
"""

MIN_PLAYERS = base_game.min_players
MAX_PLAYERS = base_game.max_players


cmds: dict[str, BotCommand] = {
    "start": BotCommand(command="start", description="Start a new lobby."),
    "help": BotCommand(command="help", description="Get help for this bot."),
    "cancel": BotCommand(command="cancel", description="Cancel current lobby."),
    "join": BotCommand(command="join", description="Join the current lobby."),
    "leave": BotCommand(command="leave", description="Leave the current lobby."),
    "create_secret_only_pick": BotCommand(
        command="create_secret_only_pick",
        description="Players secretly pick 1 of 3 random factions (at the same time).",
    ),
    "create_public_pick_ban": BotCommand(
        command="create_public_pick_ban",
        description="In order, players ban 1/3 factions and pick 1/3.",
    ),
    "create_public_ban_pick": BotCommand(
        command="create_public_ban_pick",
        description="In order, players ban 1 faction each. In reverse order, they pick",
    ),
}


class PrivateOnly(Filter):
    """Only allow commands in private."""

    async def __call__(self, message: Message) -> bool:
        if not isinstance(message, Message):
            return False
        return message.chat.type in [ChatType.PRIVATE]


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


def get_at(user: User) -> str:
    if user.username:
        return f"@{user.username}"
    return user.full_name


@router.message(Command(cmds["help"]))
async def cmd_help(message: Message) -> None:
    """Send help."""
    await message.answer(HELP_STR)


async def show_status(message: Message) -> None:
    """Show current status of the lobby."""
    chat_id = message.chat.id

    if chat_id not in state.rooms:
        await message.answer("There is no active game. /start to create a new one.")
        return

    room = state.rooms[chat_id]
    members = [await message.chat.get_member(x) for x in room.users]
    member_names = [f"{get_at(x.user)[1:]}" for x in members]
    await message.answer("Current players: " + ", ".join(member_names))


@router.message(Command(cmds["start"]), GroupOnly())
async def cmd_group_start(message: Message, bot: Bot) -> None:
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
        + "\n\nYou can /join or /leave the lobby."
        + "\nYou can also /cancel the game."
        + f"\n\n<b>Please make sure to add @{BOTNAME} in personal chats.</b>"
        + "\n\nOnce everyone has joined, create the game with some setup:\n"
        + "\n".join(
            [f"/{k} : {v.description}" for k, v in cmds.items() if "create" in k]
        )
    )
    await message.answer(reply)
    await show_status(message)


@router.message(Command(cmds["start"]))
async def cmd_personal_start(message: Message) -> None:
    """Start interacting."""
    await message.answer(
        "Hi, you will now be able to properly join TI4 games."
        " I will come back to you for secret choices."
        "\nTo start a game, add me to a group and use the start command there."
        " You can also ask for more /help if necessary."
    )


@router.message(Command(cmds["cancel"]), GroupOnly())
async def cmd_cancel(message: Message) -> None:
    """Cancel the current game."""
    chat_id = message.chat.id

    # Check for existing game
    if chat_id in state.rooms:
        del state.rooms[chat_id]
        await message.answer("Canceled game. /start to create a new one.")
    else:
        await message.answer("There is no active game.")


@router.message(Command(cmds["join"]), GroupOnly(), InLobby(state))
async def cmd_join(message: Message) -> None:
    """Join the current game."""
    chat_id = message.chat.id
    uid = message.from_user.id

    room = state.rooms[chat_id]
    if uid not in room.users:
        room.users.append(uid)

    await show_status(message)


@router.message(Command(cmds["leave"]), GroupOnly(), InLobby(state))
async def cmd_leave(message: Message) -> None:
    """Leave the current game."""
    chat_id = message.chat.id
    uid = message.from_user.id

    room = state.rooms[chat_id]
    if uid in room.users:
        room.users.remove(uid)

    await show_status(message)


WAIT_MINS: float = 1 * 60
"""How long to wait for users to add."""

REFRESH_MINS: float = 0.1
"""How often to refresh the check for added users."""


async def wait_until_users_add_me(bot: Bot, state: GlobalState, chat_id: int) -> bool:
    """Ensure that all users in the list have added the bot.

    Returns:
        True if all users have added.
        False if a timeout occurs.

    This means that the bot can reply to the users.
    Bots can't initiate chats - it's a Telegram-side limitation to stop spam.
    """
    time_start = datetime.utcnow()
    while (datetime.utcnow() - time_start).total_seconds() < 60 * WAIT_MINS:
        room = state.rooms.get(chat_id)
        # If room is canceled
        if room is None:
            await bot.send_message(chat_id, "Cancelling game.")
            return False

        # Check if we can message users
        unmessagable: list[int] = []
        for user_id in room.users:
            # If we don't have a chat, then we fail immediately
            try:
                user_chat_info = await bot.get_chat(user_id)
            except TelegramBadRequest:
                unmessagable.append(user_id)
                continue
            # If we've been blocked or muted, we might not have permissions
            perms = user_chat_info.permissions
            if perms is not None:
                if not perms.can_send_messages:
                    unmessagable.append(user_id)

        # If we can message everyone, return True
        if len(unmessagable) == 0:
            return True

        # Otherwise, ping those users
        chat = await bot.get_chat(chat_id)
        unmess_members = [await chat.get_member(x) for x in unmessagable]
        unmess_ats = [f"{get_at(x.user)}" for x in unmess_members]
        await bot.send_message(
            chat_id,
            "The following users need to send /start to me in a private chat: "
            + " ".join(unmess_ats),
        )
        await asyncio.sleep(60 * REFRESH_MINS)

    await bot.send_message(
        chat_id, f"Timed out after {WAIT_MINS} minutes. Cancelling game."
    )
    return False


async def ask_selection(
    bot: Bot, state: GlobalState, prompt: str, options: list[str], user_id: int
) -> str:
    """Ask user for faction selection."""
    # Create keyboard
    reply_kb = ReplyKeyboardBuilder()
    for opt in options:
        reply_kb.button(text=str(opt))

    await bot.send_message(
        user_id, prompt, reply_markup=reply_kb.as_markup(one_time_keyboard=True)
    )

    queue = asyncio.Queue()
    state.queues[user_id] = queue

    value = ""
    while True:
        value = await queue.get()
        if value in options:
            break
        await bot.send_message(
            user_id,
            "\n".join(["Incorrect choice, choose one of:", *options]),
            reply_markup=reply_kb.as_markup(),
        )
    from aiogram.types.reply_keyboard_remove import ReplyKeyboardRemove

    # Cleanup
    del state.queues[user_id]
    if CLEANUP_KEYBOARD:
        await bot.send_message(
            user_id,
            f"Selection: {value!r}",
            reply_markup=ReplyKeyboardRemove(remove_keyboard=True),
        )
    return value


@router.message(PrivateOnly())
async def pm_get_msg(message: Message):
    """Add stuff to message."""
    uid = message.from_user.id  # noqa
    queue = state.queues.get(uid)
    if queue is None:
        return
    await queue.put(message.text)


@router.message(Command(cmds["create_secret_only_pick"]), GroupOnly(), InLobby(state))
async def cmd_create_secret_only_pick(message: Message, bot: Bot) -> None:
    """All players pick 1 of 3 factions, at the same time."""
    chat_id = message.chat.id
    # uid = message.from_user.id  # noqa
    room = state.rooms[chat_id]
    if len(room.users) < MIN_PLAYERS:
        await message.answer(f"Need at least {MIN_PLAYERS} players; some should /join")
        return
    elif len(room.users) > MAX_PLAYERS:
        await message.answer(f"Need at most {MAX_PLAYERS} players; some should /leave")
        return

    # Wait until all users have added the bot
    if not await wait_until_users_add_me(bot=bot, state=state, chat_id=chat_id):
        return

    # Set seed and RNG
    seed = int(datetime.utcnow().timestamp() * 1000)
    rng = Random(seed)
    await message.answer(f"Using seed: {seed}")
    await message.answer_dice()

    # Create order
    user_order = rng.sample(room.users, k=len(room.users))
    order_mems = [await message.chat.get_member(x) for x in user_order]
    order_names = [f"{get_at(x.user)}" for x in order_mems]
    await message.answer(
        "Play Order:\n"
        + "\n".join([f"{i+1}. {nm}" for i, nm in enumerate(order_names)])
    )

    # Select game mode
    game = base_game

    n_per = 3

    # Select race order (basically mapping to user)
    faction_order = rng.sample(game.faction_names, k=len(game.faction_names))

    # Ask users to select stuff
    # NEW: It's now in parallel!
    sel_futures: list[asyncio.Future] = []
    for negative_i, uid in list(enumerate(user_order)):  # reversed order
        i = len(user_order) - 1 - negative_i
        i_low = i * n_per
        i_hi = min((i + 1) * n_per, len(game.faction_names))
        opts_i = faction_order[i_low:i_hi]
        sel_futures.append(
            ask_selection(
                bot=bot,
                state=state,
                prompt="Choose faction.",
                options=opts_i,
                user_id=uid,
            )
        )
        # TODO: Selection of location too?...
    selected_facs: list[str] = await asyncio.gather(*sel_futures)
    selected: dict[int, str] = {uid: fac for uid, fac in zip(user_order, selected_facs)}

    # Return results
    msg = ["Finished game setup."]
    for i, uid in enumerate(user_order):
        uname = order_names[i]
        fac = selected[uid]
        fac_link = [x for x in game.factions if x.name == fac][0].wiki
        fac_o = f'<a href="{fac_link}">{fac}</a>'
        loc = "(no location)"
        loc_o = f" at <b>{loc}</b>" if USE_LOCATION else ""
        msg.append(f"{i+1}. {uname} as <b>{fac_o}</b>{loc_o}")

    # Close game state
    msg.append("Have fun! Use /start to create a new one.")
    await message.answer("\n".join(msg), disable_web_page_preview=True)
    del state.rooms[chat_id]


@router.message(Command(cmds["create_public_pick_ban"]), GroupOnly(), InLobby(state))
async def cmd_create_public_pick_ban(message: Message, bot: Bot) -> None:
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

    # Wait until all users have added the bot
    if not await wait_until_users_add_me(bot=bot, state=state, chat_id=chat_id):
        return

    # Set seed and RNG
    seed = int(datetime.utcnow().timestamp() * 1000)
    rng = Random(seed)
    await message.answer(f"Using seed: {seed}")
    await message.answer_dice()

    # Create order
    user_order = rng.sample(room.users, k=len(room.users))
    order_mems = [await message.chat.get_member(x) for x in user_order]
    order_names = [f"{get_at(x.user)}" for x in order_mems]
    await message.answer(
        "Choosing Order:\n"
        + "\n".join([f"{i+1}. {nm}" for i, nm in enumerate(order_names)])
    )

    # Select game mode
    game = base_game

    n_per = 3
    remaining_factions = list(game.faction_names)

    # Select race order (basically mapping to user)
    # Ask users to select stuff
    selected: dict[int, str] = {}
    banned: dict[int, str] = {}
    for i, uid in list(enumerate(user_order)):  # reversed?
        try:
            user_chat = await bot.get_chat(chat_id=uid)
            user_chat
        except TelegramForbiddenError:
            pass
        # Pick
        opts_pick_i = rng.sample(remaining_factions, k=n_per)
        picked_i = await ask_selection(
            bot=bot,
            state=state,
            prompt="Choose faction to PLAY:",
            options=opts_pick_i,
            user_id=uid,
        )
        selected[uid] = picked_i
        remaining_factions.remove(picked_i)
        # Ban
        opts_ban_i = rng.sample(remaining_factions, k=n_per)
        banned_i = await ask_selection(
            bot=bot,
            state=state,
            prompt="Choose faction to BAN:",
            options=opts_ban_i,
            user_id=uid,
        )
        banned[uid] = banned_i
        remaining_factions.remove(banned_i)

        # Notify folks of pick-ban
        uname = order_names[i]
        fac = picked_i
        fac_info = [x for x in game.factions if x.name == picked_i][0]
        fac_link = fac_info.wiki
        fac_o = f'<a href="{fac_link}">{picked_i}</a>'
        await message.answer(f"{uname} picked {fac_o} and banned <b>{banned_i}</b>")
        # TODO: Selection of location too?...

    # Return results
    msg = ["Finished game setup."]
    for i, uid in enumerate(user_order):
        uname = order_names[i]
        fac = selected[uid]
        ban_i = banned[uid]
        fac_info = [x for x in game.factions if x.name == fac][0]
        fac_link = fac_info.wiki
        fac_o = f'<a href="{fac_link}">{fac}</a>'
        loc = "(no location)"
        loc_o = f" at <b>{loc}</b>" if USE_LOCATION else ""
        msg.append(f"{i+1}. {uname} banned {ban_i}, playing as <b>{fac_o}</b>{loc_o}")

    # Close game state
    msg.append("Have fun! Use /start to create a new one.")
    await message.answer("\n".join(msg), disable_web_page_preview=True)
    del state.rooms[chat_id]


@router.message(Command(cmds["create_public_ban_pick"]), GroupOnly(), InLobby(state))
async def cmd_create_public_ban_pick(message: Message, bot: Bot) -> None:
    """Create a game setup."""
    chat_id = message.chat.id
    # uid = message.from_user.id  # noqa
    room = state.rooms[chat_id]
    if len(room.users) < MIN_PLAYERS:
        await message.answer(f"Need at least {MIN_PLAYERS} players; some should /join")
        return
    elif len(room.users) > MAX_PLAYERS:
        await message.answer(f"Need at most {MAX_PLAYERS} players; some should /leave")
        return

    # Wait until all users have added the bot
    if not await wait_until_users_add_me(bot=bot, state=state, chat_id=chat_id):
        return

    # Set seed and RNG
    seed = int(datetime.utcnow().timestamp() * 1000)
    rng = Random(seed)  # noqa
    await message.answer(f"Using seed: {seed}")
    await message.answer_dice()

    # Create order
    user_order = rng.sample(room.users, k=len(room.users))
    order_mems = [await message.chat.get_member(x) for x in user_order]
    order_names = [f"{get_at(x.user)}" for x in order_mems]
    await message.answer(
        "Choosing Order:\n"
        + "\n".join([f"{i+1}. {nm}" for i, nm in enumerate(order_names)])
    )

    # Select game mode
    game = base_game

    remaining_factions = list(game.faction_names)

    selected: dict[UserID, str] = {}
    banned: dict[UserID, str] = {}  # not used right now, but maybe later

    # BAN in player order
    await message.answer("BANNING (in order):")
    for uid, uname in zip(user_order, order_names):
        ban_i = await ask_selection(
            bot=bot,
            state=state,
            prompt="Choose faction to BAN.",
            options=remaining_factions,
            user_id=uid,
        )
        banned[uid] = ban_i
        remaining_factions.remove(ban_i)
        await message.answer(f"{uname} bans {ban_i}")

    # SELECT in reverse order
    await message.answer("SELECTING (in reverse order):")
    for uid, uname in reversed(list(zip(user_order, order_names))):
        sel_i = await ask_selection(
            bot=bot,
            state=state,
            prompt="Choose faction to PLAY.",
            options=remaining_factions,
            user_id=uid,
        )
        selected[uid] = sel_i
        remaining_factions.remove(sel_i)
        await message.answer(f"{uname} plays as {sel_i}")

    # Return results
    msg = ["Finished game setup."]
    for i, uid in enumerate(user_order):
        uname = order_names[i]
        fac = selected[uid]
        # ban_i = banned[uid]
        fac_info = [x for x in game.factions if x.name == fac][0]
        fac_link = fac_info.wiki
        fac_o = f'<a href="{fac_link}">{fac}</a>'
        loc = "(no location)"
        loc_o = f" at <b>{loc}</b>" if USE_LOCATION else ""
        msg.append(f"{i+1}. {uname} playing as <b>{fac_o}</b>{loc_o}")

    # Close game state
    msg.append("Have fun! Use /start to create a new one.")
    await message.answer("\n".join(msg), disable_web_page_preview=True)
    del state.rooms[chat_id]
