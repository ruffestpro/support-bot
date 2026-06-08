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


def _retry_forum_topic_without_emoji(ex: TelegramBadRequest) -> bool:
    """Кастомный emoji в топике требует Premium у владельца бота — пробуем без иконки."""
    m = (ex.message or "").upper()
    return (
        "PREMIUM_ACCOUNT_REQUIRED" in m
        or "CUSTOM_EMOJI_NOT_ALLOWED" in m
        or "STICKER_ID_INVALID" in m
    )


async def _create_forum_topic_once(
    bot: Bot,
    config: Config,
    name: str,
    emoji_id: str | None,
) -> int:
    kwargs: dict = {
        "chat_id": config.bot.GROUP_ID,
        "name": name,
        "request_timeout": 30,
    }
    if emoji_id:
        kwargs["icon_custom_emoji_id"] = emoji_id
    forum_topic = await bot.create_forum_topic(**kwargs)
    return forum_topic.message_thread_id


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
    emoji_id = (config.bot.BOT_EMOJI_ID or "").strip() or None

    try:
        return await _create_forum_topic_once(bot, config, name, emoji_id)
    except TelegramRetryAfter as ex:
        logging.warning(ex.message)
        await asyncio.sleep(ex.retry_after)
        return await create_forum_topic(bot, config, name)

    except TelegramBadRequest as ex:
        if emoji_id and _retry_forum_topic_without_emoji(ex):
            logging.info(
                "create_forum_topic: %s — повтор без BOT_EMOJI_ID",
                ex.message,
            )
            try:
                return await _create_forum_topic_once(bot, config, name, None)
            except TelegramBadRequest as ex2:
                ex = ex2

        lowered = (ex.message or "").lower()
        if "not enough rights" in lowered:
            raise NotEnoughRightsException

        if "not a forum" in lowered:
            raise NotAForumException

        logging.error("create_forum_topic failed: %s", ex.message)
        raise CreateForumTopicException
