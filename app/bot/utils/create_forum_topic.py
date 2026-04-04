import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter

from app.config import Config
from .exceptions import CreateForumTopicException, NotEnoughRightsException, NotAForumException
from .redis import RedisStorage
from .redis.models import UserData


def is_forum_thread_stale_or_invalid_error(telegram_message: str | None) -> bool:
    """
    Ошибки Telegram при удалённом/недоступном треде форума (текст API может отличаться).
    """
    m = (telegram_message or "").lower()
    markers = (
        "message thread not found",
        "thread not found",
        "message thread id invalid",
        "message thread id is invalid",
        "bad message thread",
        "topic was deleted",
        "topic is closed",
        "topic_deleted",
        "topic_closed",
        "topic not found",
        "chat not found",
        "forum_topic_deleted",
        "discussion_missing",
    )
    return any(x in m for x in markers)


async def get_or_create_forum_topic(
        bot: Bot,
        redis: RedisStorage,
        config: Config,
        user_data: UserData,
) -> int:
    """
    Возвращает ID ветки форума. Не глотает ошибки: при неудаче создания топика
    исключение пробрасывается (см. обработчики в handlers/errors.py).
    """
    if user_data.message_thread_id is not None:
        return user_data.message_thread_id

    message_thread_id = await create_forum_topic(
        bot, config, user_data.full_name,
    )
    user_data.message_thread_id = message_thread_id
    await redis.update_user(user_data.id, user_data)
    return message_thread_id


async def create_forum_topic(bot: Bot, config: Config, name: str) -> int:
    """
    Creates a forum topic in the specified chat.

    :param bot: The Aiogram Bot instance.
    :param config: The configuration object.
    :param name: The name of the forum topic.

    :return: The message thread ID of the created forum topic.
    :raises NotEnoughRightsException: If the bot doesn't have enough rights to create a forum topic.
    :raises CreateForumTopicException: If an error occurs while creating the forum topic.
    """
    try:
        # Attempt to create a forum topic
        forum_topic = await bot.create_forum_topic(
            chat_id=config.bot.GROUP_ID,
            name=name,
            icon_custom_emoji_id=config.bot.BOT_EMOJI_ID,
            request_timeout=30,
        )
        return forum_topic.message_thread_id

    except TelegramRetryAfter as ex:
        # Handle Retry-After exception (rate limiting)
        logging.warning(ex.message)
        await asyncio.sleep(ex.retry_after)
        return await create_forum_topic(bot, config, name)

    except TelegramBadRequest as ex:
        if "not enough rights" in ex.message:
            # Raise an exception if the bot doesn't have enough rights
            raise NotEnoughRightsException

        elif "not a forum" in ex.message:
            # Raise an exception if the chat is not a forum
            raise NotAForumException

        # Raise a generic exception for other cases
        raise CreateForumTopicException
