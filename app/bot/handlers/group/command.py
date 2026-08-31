from contextlib import suppress

from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, MagicData
from aiogram.types import Message
from aiogram.utils.markdown import hcode, hbold

from app.bot.manager import Manager
from app.bot.utils.redis import RedisStorage
from app.bot.utils.redis.models import WebSessionData


def _with_open_in_bot_link(manager: Manager, text: str, start_payload: int | str | None) -> str:
    main_bot = manager.config.bot.BOT_USERNAME
    if not main_bot or start_payload is None or start_payload == "":
        return text
    link = manager.text_message.get("user_information_open_link").format(
        bot_username=main_bot,
        tg_id=start_payload,
    )
    return f"{text}\n\n{link}"


def _web_suser_payload(web_session: WebSessionData) -> int | None:
    if web_session.tg_id is not None and web_session.tg_id > 0:
        return web_session.tg_id
    if web_session.profile_ref is not None and web_session.profile_ref > 0:
        return web_session.profile_ref
    return None


router_id = Router()
router_id.message.filter(
    F.chat.type.in_(["group", "supergroup"]),
)


@router_id.message(Command("id"))
async def handler(message: Message) -> None:
    """
    Sends chat ID in response to the /id command.

    :param message: Message object.
    :return: None
    """
    await message.reply(hcode(message.chat.id))


router = Router()
router.message.filter(
    F.message_thread_id.is_not(None),
    F.chat.type.in_(["group", "supergroup"]),
    MagicData(F.event_chat.id == F.config.bot.GROUP_ID),  # type: ignore
)


@router.message(Command("silent"))
async def handler(message: Message, manager: Manager, redis: RedisStorage) -> None:
    """
    Toggles silent mode for a user in the group.
    If silent mode is disabled, it will be enabled, and vice versa.

    :param message: Message object.
    :param manager: Manager object.
    :param redis: RedisStorage object.
    :return: None
    """
    user_data = await redis.get_by_message_thread_id(message.message_thread_id)
    web_session = None if user_data else await redis.get_web_by_message_thread_id(
        message.message_thread_id,
    )
    if not user_data and not web_session:
        return None  # noqa

    target = user_data or web_session
    assert target is not None

    if target.message_silent_mode:
        text = manager.text_message.get("silent_mode_disabled")
        with suppress(TelegramBadRequest):
            await message.reply(text)
            if target.message_silent_id is not None:
                await message.bot.unpin_chat_message(
                    chat_id=message.chat.id,
                    message_id=target.message_silent_id,
                )
        target.message_silent_mode = False
        target.message_silent_id = None
    else:
        text = manager.text_message.get("silent_mode_enabled")
        with suppress(TelegramBadRequest):
            msg = await message.reply(text)
            await msg.pin(disable_notification=True)
            target.message_silent_mode = True
            target.message_silent_id = msg.message_id

    if user_data:
        await redis.update_user(user_data.id, user_data)
    else:
        await redis.update_web_session(web_session)  # type: ignore[arg-type]


@router.message(Command("information"))
async def handler(message: Message, manager: Manager, redis: RedisStorage) -> None:
    """
    Sends user information in response to the /information command.

    :param message: Message object.
    :param manager: Manager object.
    :param redis: RedisStorage object.
    :return: None
    """
    user_data = await redis.get_by_message_thread_id(message.message_thread_id)
    web_session = None if user_data else await redis.get_web_by_message_thread_id(
        message.message_thread_id,
    )
    if not user_data and not web_session:
        return None  # noqa

    if user_data:
        format_data = user_data.to_dict()
        format_data["full_name"] = hbold(format_data["full_name"])
        text = manager.text_message.get("user_information").format_map(format_data)
        await message.reply(_with_open_in_bot_link(manager, text, user_data.id))
        return

    assert isinstance(web_session, WebSessionData)
    lines = [
        f"🌐 {hbold('Веб-ЛК')}",
        f"Имя: {hbold(web_session.display_name)}",
        f"Identity: {hcode(web_session.identity_id)}",
    ]
    if web_session.email:
        lines.append(f"Email: {hcode(web_session.email)}")
    if web_session.tg_id is not None:
        lines.append(f"Telegram ID: {hcode(str(web_session.tg_id))}")
    lines.append(f"Заблокирован: {hcode(str(web_session.is_banned))}")
    text = "\n".join(lines)
    await message.reply(_with_open_in_bot_link(manager, text, _web_suser_payload(web_session)))


@router.message(Command(commands=["ban"]))
async def handler(message: Message, manager: Manager, redis: RedisStorage) -> None:
    """
    Toggles the ban status for a user in the group.
    If the user is banned, they will be unbanned, and vice versa.

    :param message: Message object.
    :param manager: Manager object.
    :param redis: RedisStorage object.
    :return: None
    """
    user_data = await redis.get_by_message_thread_id(message.message_thread_id)
    web_session = None if user_data else await redis.get_web_by_message_thread_id(
        message.message_thread_id,
    )
    if not user_data and not web_session:
        return None  # noqa

    if user_data:
        if user_data.is_banned:
            user_data.is_banned = False
            text = manager.text_message.get("user_unblocked")
        else:
            user_data.is_banned = True
            text = manager.text_message.get("user_blocked")
        await message.reply(text)
        await redis.update_user(user_data.id, user_data)
        return

    assert isinstance(web_session, WebSessionData)
    if web_session.is_banned:
        web_session.is_banned = False
        text = manager.text_message.get("user_unblocked")
    else:
        web_session.is_banned = True
        text = manager.text_message.get("user_blocked")
    await message.reply(text)
    await redis.update_web_session(web_session)
