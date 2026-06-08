import asyncio
from typing import Optional

from aiogram import Router, F
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import MagicData
from aiogram.types import Message
from aiogram.utils.markdown import hlink

from app.bot.manager import Manager
from app.bot.types.album import Album
from app.bot.utils.redis import RedisStorage
from app.bot.utils.redis.redis import GROQ_OPERATOR_CONTENT_PREFIX

router = Router()
router.message.filter(
    MagicData(F.event_chat.id == F.config.bot.GROUP_ID),  # type: ignore
    F.chat.type.in_(["group", "supergroup"]),
    F.message_thread_id.is_not(None),
)


@router.message(F.forum_topic_created)
async def handler(message: Message, manager: Manager, redis: RedisStorage) -> None:
    await asyncio.sleep(3)
    user_data = await redis.get_by_message_thread_id(message.message_thread_id)
    web_session = None if user_data else await redis.get_web_by_message_thread_id(
        message.message_thread_id,
    )

    if user_data:
        url = (
            f"https://t.me/{user_data.username[1:]}"
            if user_data.username != "-"
            else f"tg://user?id={user_data.id}"
        )
        text = manager.text_message.get("user_started_bot")
        pin_text = text.format(name=hlink(user_data.full_name, url))
        thread_id = user_data.message_thread_id
    elif web_session:
        label = web_session.display_name or web_session.identity_id[:8]
        pin_text = f"🌐 <b>Веб-ЛК:</b> {label}\n<code>{web_session.identity_id}</code>"
        thread_id = web_session.message_thread_id
    else:
        return None  # noqa

    pin_message = await message.bot.send_message(
        chat_id=manager.config.bot.GROUP_ID,
        text=pin_text,
        message_thread_id=thread_id,
    )
    await pin_message.pin()


@router.message(F.pinned_message | F.forum_topic_edited | F.forum_topic_closed | F.forum_topic_reopened)
async def handler(message: Message) -> None:
    """
    Delete service messages such as pinned, edited, closed, or reopened forum topics.

    :param message: Message object.
    :return: None
    """
    await message.delete()


@router.message(F.media_group_id, F.from_user[F.is_bot.is_(False)])
@router.message(F.media_group_id.is_(None), F.from_user[F.is_bot.is_(False)])
async def handler(message: Message, manager: Manager, redis: RedisStorage, album: Optional[Album] = None) -> None:
    """
    Handles user messages and sends them to the respective user.
    If silent mode is enabled for the user, the messages are ignored.

    :param message: Message object.
    :param manager: Manager object.
    :param redis: RedisStorage object.
    :param album: Album object or None.
    :return: None
    """
    user_data = await redis.get_by_message_thread_id(message.message_thread_id)
    web_session = None if user_data else await redis.get_web_by_message_thread_id(
        message.message_thread_id,
    )
    if not user_data and not web_session:
        return None  # noqa

    if user_data and user_data.message_silent_mode:
        return
    if web_session and web_session.message_silent_mode:
        return

    text = manager.text_message.get("message_sent_to_user")

    if web_session:
        staff_text = message.text or message.caption
        if not staff_text and album:
            staff_text = "[Оператор прислал вложение — откройте топик в Telegram]"
        if staff_text and staff_text.strip():
            await redis.web_append_message(
                web_session.identity_id,
                "staff",
                staff_text.strip(),
            )
            if manager.config.groq.enabled and not album:
                await redis.groq_append_turn(
                    web_session.identity_id,
                    "assistant",
                    f"{GROQ_OPERATOR_CONTENT_PREFIX}: {staff_text.strip()}",
                )
                await redis.groq_mark_operator_engaged(web_session.identity_id)
        msg = await message.reply(text)
        await asyncio.sleep(5)
        await msg.delete()
        return

    try:
        if not album:
            await message.copy_to(chat_id=user_data.id)
        else:
            await album.copy_to(chat_id=user_data.id)
    except TelegramAPIError as ex:
        lowered = (ex.message or "").lower()
        if "blocked" in lowered:
            text = manager.text_message.get("blocked_by_user")
        else:
            text = manager.text_message.get("message_not_sent")
    else:
        if manager.config.groq.enabled and not album:
            staff_text = message.text or message.caption
            if staff_text and staff_text.strip():
                await redis.groq_append_turn(
                    user_data.id,
                    "assistant",
                    f"{GROQ_OPERATOR_CONTENT_PREFIX}: {staff_text.strip()}",
                )
                await redis.groq_mark_operator_engaged(user_data.id)

    msg = await message.reply(text)
    await asyncio.sleep(5)
    await msg.delete()
