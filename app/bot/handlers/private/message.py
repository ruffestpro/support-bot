import asyncio
import logging

from aiogram import Router, F
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.types import Message

from app.bot.manager import Manager
from app.bot.types.album import Album
from app.bot.utils.create_forum_topic import (
    create_forum_topic,
    get_or_create_forum_topic,
)
from app.bot.utils.groq import groq_chat_completion, groq_reply_for_telegram_html
from app.bot.utils.redis import RedisStorage
from app.bot.utils.redis.models import UserData

logger = logging.getLogger(__name__)

# Длина текста ответа ИИ до HTML-экранирования (заголовок + запас под лимит 4096)
_GROQ_STAFF_BODY_MAX = 3400

router = Router()
router.message.filter(F.chat.type == "private", StateFilter(None))


@router.edited_message()
async def handle_edited_message(message: Message, manager: Manager) -> None:
    """
    Handle edited messages.

    :param message: The edited message.
    :param manager: Manager object.
    :return: None
    """
    # Get the text for the edited message
    text = manager.text_message.get("message_edited")
    # Reply to the edited message with the specified text
    msg = await message.reply(text)
    # Wait for 5 seconds before deleting the reply
    await asyncio.sleep(5)
    # Delete the reply to the edited message
    await msg.delete()


@router.message(F.media_group_id)
@router.message(F.media_group_id.is_(None))
async def handle_incoming_message(
        message: Message,
        manager: Manager,
        redis: RedisStorage,
        user_data: UserData,
        album: Album | None = None,
) -> None:
    """
    Handles incoming messages and copies them to the forum topic.
    If the user is banned, the messages are ignored.

    :param message: The incoming message.
    :param manager: Manager object.
    :param redis: RedisStorage object.
    :param user_data: UserData object.
    :param album: Album object or None.
    :return: None
    """
    # Check if the user is banned
    if user_data.is_banned:
        return

    async def copy_message_to_topic():
        """
        Copies the message or album to the forum topic.
        If no album is provided, the message is copied. Otherwise, the album is copied.
        """
        message_thread_id = await get_or_create_forum_topic(
            message.bot,
            redis,
            manager.config,
            user_data,
        )

        if not album:
            await message.forward(
                chat_id=manager.config.bot.GROUP_ID,
                message_thread_id=message_thread_id,
            )
        else:
            await album.copy_to(
                chat_id=manager.config.bot.GROUP_ID,
                message_thread_id=message_thread_id,
            )

    try:
        await copy_message_to_topic()
    except TelegramBadRequest as ex:
        if "message thread not found" in ex.message:
            user_data.message_thread_id = await create_forum_topic(
                message.bot,
                manager.config,
                user_data.full_name,
            )
            await redis.update_user(user_data.id, user_data)
            await copy_message_to_topic()
        else:
            raise

    # Send a confirmation message to the user
    text = manager.text_message.get("message_sent")
    # Reply to the edited message with the specified text
    msg = await message.reply(text)
    # Wait for 5 seconds before deleting the reply
    await asyncio.sleep(5)
    # Delete the reply to the edited message
    await msg.delete()

    if (
        manager.config.groq.enabled
        and not album
        and message.text
    ):
        history = await redis.groq_get_history(user_data.id)
        ai_text = await groq_chat_completion(
            manager.config.groq,
            message.text,
            history=history,
        )
        await redis.groq_append_turn(user_data.id, "user", message.text)
        if ai_text:
            await redis.groq_append_turn(user_data.id, "assistant", ai_text)
            try:
                await message.answer(
                    groq_reply_for_telegram_html(ai_text),
                    parse_mode=ParseMode.HTML,
                )
            except TelegramBadRequest:
                logger.exception("Failed to send Groq reply to user")
            else:
                # Операторы в топике видят тот же ответ ИИ (в ЛС его видит только пользователь)
                if user_data.message_thread_id is not None:
                    header = manager.text_message.get("groq_staff_header")
                    plain = ai_text
                    if len(plain) > _GROQ_STAFF_BODY_MAX:
                        plain = plain[: _GROQ_STAFF_BODY_MAX - 1] + "…"
                    staff_text = f"{header}\n\n{groq_reply_for_telegram_html(plain)}"
                    try:
                        await message.bot.send_message(
                            chat_id=manager.config.bot.GROUP_ID,
                            message_thread_id=user_data.message_thread_id,
                            text=staff_text,
                            parse_mode=ParseMode.HTML,
                        )
                    except TelegramBadRequest:
                        logger.exception("Failed to mirror Groq reply to support topic")
