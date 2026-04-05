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
    is_forum_thread_stale_or_invalid_error,
)
from app.bot.utils.exceptions import (
    CreateForumTopicException,
    NotAForumException,
    NotEnoughRightsException,
)
from app.bot.utils.groq import (
    groq_chat_completion,
    groq_vision_completion,
    groq_reply_for_telegram_html,
)
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

    # Антиспам: скользящее окно rate-limit
    if not await redis.spam_check_and_record(user_data.id):
        wait = await redis.spam_remaining_wait(user_data.id)
        text = manager.text_message.get("rate_limit_exceeded").format(wait=wait)
        try:
            warn = await message.reply(text, parse_mode=ParseMode.HTML)
            await asyncio.sleep(5)
            await warn.delete()
        except TelegramBadRequest:
            pass
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

    forwarded_ok = False
    try:
        await copy_message_to_topic()
        forwarded_ok = True
    except TelegramBadRequest as ex:
        logger.warning("TelegramBadRequest при доставке в топик: %r", ex.message)
        if is_forum_thread_stale_or_invalid_error(ex.message):
            user_data.message_thread_id = None
            await redis.update_user(user_data.id, user_data)
            try:
                await copy_message_to_topic()
                forwarded_ok = True
            except NotEnoughRightsException:
                raise
            except (CreateForumTopicException, NotAForumException) as ex2:
                logger.warning("Топик недоступен после сброса удалённого треда: %s", ex2)
                user_data.message_thread_id = None
                await redis.update_user(user_data.id, user_data)
            except TelegramBadRequest as ex2:
                logger.warning("Повторная TelegramBadRequest после сброса треда: %r", ex2.message)
                if is_forum_thread_stale_or_invalid_error(ex2.message):
                    user_data.message_thread_id = None
                    await redis.update_user(user_data.id, user_data)
                else:
                    raise
        else:
            raise
    except (CreateForumTopicException, NotAForumException):
        user_data.message_thread_id = None
        await redis.update_user(user_data.id, user_data)
        logger.warning("Топик форума недоступен (создание/чат)", exc_info=True)

    if not forwarded_ok:
        return

    # Send a confirmation message to the user
    text = manager.text_message.get("message_sent")
    # Reply to the edited message with the specified text
    msg = await message.reply(text)
    # Wait for 5 seconds before deleting the reply
    await asyncio.sleep(5)
    # Delete the reply to the edited message
    await msg.delete()

    if (
        not album
        and not await redis.groq_is_operator_engaged(user_data.id)
        and await redis.groq_cooldown_ok(user_data.id)
    ):
        ai_text: str | None = None
        user_turn: str | None = None

        # — текстовое сообщение → обычная текстовая модель
        if manager.config.groq.enabled and message.text:
            history = await redis.groq_get_history(user_data.id)
            ai_text = await groq_chat_completion(
                manager.config.groq,
                message.text,
                history=history,
            )
            user_turn = message.text

        # — фото + подпись → vision-модель
        elif (
            manager.config.groq.vision_enabled
            and message.photo
            and message.caption
        ):
            photo = message.photo[-1]  # наибольшее разрешение
            try:
                file = await message.bot.get_file(photo.file_id)
                buf = await message.bot.download_file(file.file_path)
                image_bytes = buf.read() if hasattr(buf, "read") else bytes(buf)
            except Exception:
                logger.warning("Не удалось скачать фото для vision Groq", exc_info=True)
                image_bytes = None

            if image_bytes:
                history = await redis.groq_get_history(user_data.id)
                ai_text = await groq_vision_completion(
                    manager.config.groq,
                    caption=message.caption,
                    image_bytes=image_bytes,
                    history=history,
                )
                user_turn = f"[фото] {message.caption}"

        # — только фото без подписи → пропуск (ai_text остаётся None)

        if user_turn:
            await redis.groq_append_turn(user_data.id, "user", user_turn)

        if ai_text:
            await redis.groq_cooldown_set(user_data.id)
            await redis.groq_append_turn(user_data.id, "assistant", ai_text)
            try:
                await message.answer(
                    groq_reply_for_telegram_html(ai_text),
                    parse_mode=ParseMode.HTML,
                )
            except TelegramBadRequest:
                logger.exception("Failed to send Groq reply to user")
            else:
                # Операторы в топике видят тот же ответ ИИ
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
