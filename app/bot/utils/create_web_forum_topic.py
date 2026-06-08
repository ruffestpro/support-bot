from aiogram import Bot

from app.config import Config
from .create_forum_topic import create_forum_topic
from .redis import RedisStorage
from .redis.models import WebSessionData


def _topic_title(session: WebSessionData) -> str:
    if session.email:
        title = f"Web · {session.email}"
    elif session.tg_id is not None:
        title = f"Web · TG {session.tg_id}"
    else:
        title = f"Web · {session.identity_id[:8]}"
    return title[:128]


async def get_or_create_web_forum_topic(
    bot: Bot,
    redis: RedisStorage,
    config: Config,
    session: WebSessionData,
) -> int:
    if session.message_thread_id is not None:
        return session.message_thread_id

    message_thread_id = await create_forum_topic(
        bot, config, _topic_title(session),
    )
    session.message_thread_id = message_thread_id
    await redis.update_web_session(session)
    return message_thread_id
