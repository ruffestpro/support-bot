import logging
import uuid
from html import escape

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BufferedInputFile
from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

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
from app.web.auth import CabinetIdentity, lookup_cabinet_suser_ref, verify_cabinet_request
from app.web.groq import maybe_groq_web_reply, maybe_groq_web_vision_reply
from app.web.images import (
    ALLOWED_IMAGE_MIME,
    MAX_IMAGE_BYTES,
    image_api_path,
    resolve_web_chat_image,
    save_web_chat_image,
)
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
    *,
    request: Request | None = None,
    config: Config | None = None,
    force_profile_lookup: bool = False,
) -> WebSessionData:
    existing = await redis.get_web_session(identity.id)
    if existing:
        if identity.email and existing.email != identity.email:
            existing.email = identity.email
        if identity.tg_id is not None and existing.tg_id != identity.tg_id:
            existing.tg_id = identity.tg_id
        existing.display_name = _display_name(identity)
        await _maybe_fill_profile_ref(
            existing,
            identity,
            request=request,
            config=config,
            force=force_profile_lookup,
        )
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
    await _maybe_fill_profile_ref(
        session,
        identity,
        request=request,
        config=config,
        force=True,
    )
    await redis.update_web_session(session)
    return session


async def _maybe_fill_profile_ref(
    session: WebSessionData,
    identity: CabinetIdentity,
    *,
    request: Request | None,
    config: Config | None,
    force: bool,
) -> None:
    if identity.tg_id is not None and identity.tg_id > 0:
        session.profile_ref = identity.tg_id
        session.profile_lookup_done = True
        return
    if session.profile_ref is not None:
        session.profile_lookup_done = True
        return
    if session.profile_lookup_done and not force:
        return
    if request is None or config is None:
        return
    session.profile_ref = await lookup_cabinet_suser_ref(request, config)
    session.profile_lookup_done = True


async def _ensure_not_spam(redis: RedisStorage, identity_id: str) -> None:
    if not await redis.web_spam_check_and_record(identity_id):
        wait = await redis.web_spam_remaining_wait(identity_id)
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many messages. Retry in {wait}s",
            headers={"Retry-After": str(wait)},
        )


async def _deliver_text_to_topic(
    *,
    bot: Bot,
    config: Config,
    redis: RedisStorage,
    session: WebSessionData,
    identity: CabinetIdentity,
    text: str,
) -> None:
    topic_text = f"{_staff_topic_header(identity)}\n\n{text}"

    async def _send() -> None:
        thread_id = await get_or_create_web_forum_topic(
            bot, redis, config, session,
        )
        await bot.send_message(
            chat_id=config.bot.GROUP_ID,
            message_thread_id=thread_id,
            text=topic_text,
            parse_mode=ParseMode.HTML,
        )

    try:
        await _send()
    except TelegramBadRequest as ex:
        logger.warning("TelegramBadRequest при доставке web-сообщения: %r", ex.message)
        if is_forum_thread_stale_or_invalid_error(ex.message):
            session.message_thread_id = None
            await redis.update_web_session(session)
            try:
                await _send()
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


async def _deliver_photo_to_topic(
    *,
    bot: Bot,
    config: Config,
    redis: RedisStorage,
    session: WebSessionData,
    identity: CabinetIdentity,
    image_bytes: bytes,
    filename: str,
    text: str,
) -> None:
    header = _staff_topic_header(identity)
    if text:
        caption = f"{header}\n\n{escape(text)}"
    else:
        caption = header

    photo = BufferedInputFile(image_bytes, filename=filename)

    async def _send() -> None:
        thread_id = await get_or_create_web_forum_topic(
            bot, redis, config, session,
        )
        await bot.send_photo(
            chat_id=config.bot.GROUP_ID,
            message_thread_id=thread_id,
            photo=photo,
            caption=caption,
            parse_mode=ParseMode.HTML,
        )

    try:
        await _send()
    except TelegramBadRequest as ex:
        logger.warning("TelegramBadRequest при доставке web-фото: %r", ex.message)
        if is_forum_thread_stale_or_invalid_error(ex.message):
            session.message_thread_id = None
            await redis.update_web_session(session)
            try:
                await _send()
            except TelegramBadRequest:
                logger.exception("Повторная ошибка доставки web-фото в топик")
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
        logger.error("Ошибка forum topic для web-фото: %s", ex)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail=str(ex),
        ) from ex


def create_web_app(bot: Bot, config: Config, redis_storage: RedisStorage) -> FastAPI:
    app = FastAPI(title="Support Web API", version="1.0.0")
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
        request: Request,
        identity: CabinetIdentity = Depends(cabinet_identity),
        since: str | None = Query(default=None, description="ISO timestamp; вернуть только новее"),
    ) -> MessagesListResponse:
        await _get_or_init_session(
            redis_storage,
            identity,
            request=request,
            config=config,
        )
        messages = await redis_storage.web_list_messages(identity.id, since=since)
        return MessagesListResponse(
            messages=[ChatMessageOut(**m.to_dict()) for m in messages],
        )

    @app.get("/support/messages/{message_id}/image")
    async def get_message_image(
        message_id: str,
        identity: CabinetIdentity = Depends(cabinet_identity),
    ) -> FileResponse:
        msg = await redis_storage.web_get_message(identity.id, message_id)
        if msg is None or not msg.image_url:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Image not found")

        path = resolve_web_chat_image(identity.id, message_id)
        if path is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Image not found")

        media_type = next(
            (mime for mime, ext in ALLOWED_IMAGE_MIME.items() if path.name.endswith(ext)),
            "application/octet-stream",
        )
        return FileResponse(path, media_type=media_type)

    @app.post("/support/messages", response_model=PostMessageResponse)
    async def post_message(
        request: Request,
        identity: CabinetIdentity = Depends(cabinet_identity),
    ) -> PostMessageResponse:
        session = await _get_or_init_session(
            redis_storage,
            identity,
            request=request,
            config=config,
            force_profile_lookup=True,
        )
        if session.is_banned:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Support access blocked")

        await _ensure_not_spam(redis_storage, identity.id)

        content_type = (request.headers.get("content-type") or "").lower()
        if content_type.startswith("multipart/form-data"):
            form = await request.form()
            text = str(form.get("text") or "").strip()
            upload = form.get("image")
            if upload is None or not hasattr(upload, "read"):
                raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Image file required")

            image_bytes = await upload.read()
            if not image_bytes:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Empty image file")
            if len(image_bytes) > MAX_IMAGE_BYTES:
                raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Image too large")

            mime = (getattr(upload, "content_type", None) or "").split(";")[0].strip().lower()
            if mime not in ALLOWED_IMAGE_MIME:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Unsupported image type")

            if not text:
                text = ""

            message_id = uuid.uuid4().hex
            save_web_chat_image(identity.id, message_id, image_bytes, mime)
            image_url = image_api_path(message_id)

            await _deliver_photo_to_topic(
                bot=bot,
                config=config,
                redis=redis_storage,
                session=session,
                identity=identity,
                image_bytes=image_bytes,
                filename=f"photo{ALLOWED_IMAGE_MIME[mime]}",
                text=text,
            )

            user_msg = await redis_storage.web_append_message(
                identity.id,
                "user",
                text,
                image_url=image_url,
                message_id=message_id,
            )
            session = await redis_storage.get_web_session(identity.id) or session

            if text:
                await maybe_groq_web_vision_reply(
                    bot=bot,
                    config=config,
                    redis=redis_storage,
                    identity_id=identity.id,
                    session=session,
                    user_text=text,
                    image_bytes=image_bytes,
                    image_mime=mime,
                )
            return PostMessageResponse(message=ChatMessageOut(**user_msg.to_dict()))

        try:
            body = PostMessageRequest.model_validate(await request.json())
        except Exception as ex:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid request body") from ex

        text = body.text.strip()
        await _deliver_text_to_topic(
            bot=bot,
            config=config,
            redis=redis_storage,
            session=session,
            identity=identity,
            text=text,
        )

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
