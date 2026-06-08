import logging

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware

from app.config import Config
from app.bot.utils.create_forum_topic import is_forum_thread_stale_or_invalid_error
from app.bot.utils.create_web_forum_topic import get_or_create_web_forum_topic
from app.bot.utils.exceptions import (
    CreateForumTopicException,
    NotAForumException,
    NotEnoughRightsException,
)
from app.bot.utils.redis import RedisStorage
from app.bot.utils.redis.models import WebSessionData
from app.web.auth import CabinetIdentity, verify_cabinet_request
from app.web.groq import maybe_groq_web_reply
from app.web.schemas import (
    ChatMessageOut,
    MessagesListResponse,
    PostMessageRequest,
    PostMessageResponse,
)

logger = logging.getLogger(__name__)


def _display_name(identity: CabinetIdentity) -> str:
    if identity.email:
        return identity.email
    if identity.tg_id is not None:
        return f"TG {identity.tg_id}"
    return f"ID {identity.id[:8]}"


def _staff_topic_header(identity: CabinetIdentity) -> str:
    lines = ["🌐 <b>Личный кабинет</b>"]
    if identity.email:
        lines.append(f"Email: <code>{identity.email}</code>")
    if identity.tg_id is not None:
        lines.append(f"Telegram ID: <code>{identity.tg_id}</code>")
    lines.append(f"Identity: <code>{identity.id}</code>")
    return "\n".join(lines)


async def _get_or_init_session(
    redis: RedisStorage,
    identity: CabinetIdentity,
) -> WebSessionData:
    existing = await redis.get_web_session(identity.id)
    if existing:
        if identity.email and existing.email != identity.email:
            existing.email = identity.email
        if identity.tg_id is not None and existing.tg_id != identity.tg_id:
            existing.tg_id = identity.tg_id
        existing.display_name = _display_name(identity)
        await redis.update_web_session(existing)
        return existing

    session = WebSessionData(
        identity_id=identity.id,
        display_name=_display_name(identity),
        email=identity.email,
        tg_id=identity.tg_id,
        message_thread_id=None,
        message_silent_id=None,
        message_silent_mode=False,
        is_banned=False,
    )
    await redis.update_web_session(session)
    return session


def create_web_app(bot: Bot, config: Config, redis_storage: RedisStorage) -> FastAPI:
    app = FastAPI(title="R2D2 Support Web API", version="1.0.0")
    app.state.bot = bot
    app.state.config = config
    app.state.redis = redis_storage

    if config.web.CORS_ORIGINS:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(config.web.CORS_ORIGINS),
            allow_credentials=True,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["*"],
        )

    async def cabinet_identity(request: Request) -> CabinetIdentity:
        return await verify_cabinet_request(request, config)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/support/messages", response_model=MessagesListResponse)
    async def list_messages(
        identity: CabinetIdentity = Depends(cabinet_identity),
        since: str | None = Query(default=None, description="ISO timestamp; вернуть только новее"),
    ) -> MessagesListResponse:
        messages = await redis_storage.web_list_messages(identity.id, since=since)
        return MessagesListResponse(
            messages=[ChatMessageOut(**m.to_dict()) for m in messages],
        )

    @app.post("/support/messages", response_model=PostMessageResponse)
    async def post_message(
        body: PostMessageRequest,
        identity: CabinetIdentity = Depends(cabinet_identity),
    ) -> PostMessageResponse:
        session = await _get_or_init_session(redis_storage, identity)
        if session.is_banned:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Support access blocked")

        if not await redis_storage.web_spam_check_and_record(identity.id):
            wait = await redis_storage.web_spam_remaining_wait(identity.id)
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many messages. Retry in {wait}s",
                headers={"Retry-After": str(wait)},
            )

        text = body.text.strip()
        topic_text = f"{_staff_topic_header(identity)}\n\n{text}"

        async def _deliver_to_topic() -> None:
            thread_id = await get_or_create_web_forum_topic(
                bot, redis_storage, config, session,
            )
            await bot.send_message(
                chat_id=config.bot.GROUP_ID,
                message_thread_id=thread_id,
                text=topic_text,
                parse_mode=ParseMode.HTML,
            )

        try:
            await _deliver_to_topic()
        except TelegramBadRequest as ex:
            logger.warning("TelegramBadRequest при доставке web-сообщения: %r", ex.message)
            if is_forum_thread_stale_or_invalid_error(ex.message):
                session.message_thread_id = None
                await redis_storage.update_web_session(session)
                try:
                    await _deliver_to_topic()
                except TelegramBadRequest:
                    logger.exception("Повторная ошибка доставки web-сообщения в топик")
                    raise HTTPException(
                        status.HTTP_502_BAD_GATEWAY,
                        detail="Cannot deliver message to support",
                    ) from ex
            else:
                raise HTTPException(
                    status.HTTP_502_BAD_GATEWAY,
                    detail="Cannot deliver message to support",
                ) from ex
        except (CreateForumTopicException, NotEnoughRightsException, NotAForumException) as ex:
            logger.error("Ошибка forum topic для web-ЛК: %s", ex)
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                detail=str(ex),
            ) from ex

        user_msg = await redis_storage.web_append_message(identity.id, "user", text)
        session = await redis_storage.get_web_session(identity.id) or session
        await maybe_groq_web_reply(
            bot=bot,
            config=config,
            redis=redis_storage,
            identity_id=identity.id,
            session=session,
            user_text=text,
        )
        return PostMessageResponse(message=ChatMessageOut(**user_msg.to_dict()))

    return app
