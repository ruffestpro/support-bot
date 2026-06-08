import logging

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest

from app.bot.utils.groq import groq_chat_completion, groq_reply_for_telegram_html
from app.bot.utils.redis import RedisStorage
from app.bot.utils.redis.models import WebSessionData
from app.bot.utils.texts import TextMessage
from app.config import Config

logger = logging.getLogger(__name__)

_GROQ_STAFF_BODY_MAX = 3400


async def maybe_groq_web_reply(
    *,
    bot: Bot,
    config: Config,
    redis: RedisStorage,
    identity_id: str,
    session: WebSessionData,
    user_text: str,
) -> None:
    """Первая линия Groq для веб-ЛК: ответ в чат ЛК и зеркало в топик операторов."""
    if not config.groq.enabled or not user_text.strip():
        return
    if await redis.groq_is_operator_engaged(identity_id):
        return
    if not await redis.groq_cooldown_ok(identity_id):
        return

    history = await redis.groq_get_history(identity_id)
    ai_text = await groq_chat_completion(
        config.groq,
        user_text.strip(),
        history=history,
    )
    await redis.groq_append_turn(identity_id, "user", user_text.strip())
    if not ai_text:
        return

    await redis.groq_cooldown_set(identity_id)
    await redis.groq_append_turn(identity_id, "assistant", ai_text)
    await redis.web_append_message(identity_id, "ai", ai_text)

    thread_id = session.message_thread_id
    if thread_id is None:
        return

    texts = TextMessage("ru")
    header = texts.get("groq_staff_header")
    plain = ai_text
    if len(plain) > _GROQ_STAFF_BODY_MAX:
        plain = plain[: _GROQ_STAFF_BODY_MAX - 1] + "…"
    staff_text = f"{header}\n\n{groq_reply_for_telegram_html(plain)}"
    try:
        await bot.send_message(
            chat_id=config.bot.GROUP_ID,
            message_thread_id=thread_id,
            text=staff_text,
            parse_mode=ParseMode.HTML,
        )
    except TelegramBadRequest:
        logger.exception("Не удалось отправить ответ Groq в топик (web-ЛК)")
