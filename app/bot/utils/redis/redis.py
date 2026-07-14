import json
import time
import uuid
from datetime import datetime, timezone, timedelta

from redis.asyncio import Redis

from .models import UserData, WebSessionData, WebChatMessage


GROQ_OPERATOR_CONTENT_PREFIX = "[Поддержка (оператор)]"


class RedisStorage:
    """Class for managing user data storage using Redis."""

    NAME = "users"
    WEB_NAME = "web_users"
    WEB_MSG_PREFIX = "web_msgs"
    WEB_MSG_MAX_ITEMS = 500
    WEB_MSG_TTL_SEC = 60 * 60 * 24 * 30
    GROQ_CTX_PREFIX = "groq_ctx"
    GROQ_OP_PREFIX = "groq_op"
    GROQ_CTX_MAX_ITEMS = 48
    GROQ_CTX_TTL_SEC = 60 * 60 * 24 * 14

    # Антиспам
    SPAM_PREFIX = "spam"
    GROQ_CD_PREFIX = "groq_cd"

    def __init__(
        self,
        redis: Redis,
        groq_operator_lock_sec: int = 3600,
        spam_max_messages: int = 5,
        spam_window_sec: int = 30,
        groq_cooldown_sec: int = 0,
    ) -> None:
        """
        Initializes the RedisStorage instance.

        :param redis: The Redis instance to be used for data storage.
        :param groq_operator_lock_sec: TTL ключа блокировки ИИ после сообщения оператора.
        :param spam_max_messages: Максимум сообщений за spam_window_sec.
        :param spam_window_sec: Размер скользящего окна для rate-limit (сек).
        :param groq_cooldown_sec: Минимальный интервал между ответами ИИ (сек), 0 = без ограничений.
        """
        self.redis = redis
        self._groq_operator_lock_sec = groq_operator_lock_sec
        self._spam_max = spam_max_messages
        self._spam_window = spam_window_sec
        self._groq_cooldown = groq_cooldown_sec

    async def _get(self, name: str, key: str | int) -> bytes | None:
        """
        Retrieves data from Redis.

        :param name: The name of the Redis hash.
        :param key: The key to be retrieved.
        :return: The retrieved data or None if not found.
        """
        async with self.redis.client() as client:
            return await client.hget(name, key)

    async def _set(self, name: str, key: str | int, value: any) -> None:
        """
        Sets data in Redis.

        :param name: The name of the Redis hash.
        :param key: The key to be set.
        :param value: The value to be set.
        """
        async with self.redis.client() as client:
            await client.hset(name, key, value)

    async def _update_index(self, message_thread_id: int, user_id: int) -> None:
        """
        Updates the user index in Redis.

        :param message_thread_id: The ID of the message thread.
        :param user_id: The ID of the user to be updated in the index.
        """
        index_key = f"{self.NAME}_index_{message_thread_id}"
        await self._set(index_key, user_id, "1")

    async def get_by_message_thread_id(self, message_thread_id: int) -> UserData | None:
        """
        Retrieves user data based on message thread ID.

        :param message_thread_id: The ID of the message thread.
        :return: The user data or None if not found.
        """
        user_id = await self._get_user_id_by_message_thread_id(message_thread_id)
        return None if user_id is None else await self.get_user(user_id)

    async def _get_user_id_by_message_thread_id(self, message_thread_id: int) -> int | None:
        """
        Retrieves user ID based on message thread ID.

        :param message_thread_id: The ID of the message thread.
        :return: The user ID or None if not found.
        """
        index_key = f"{self.NAME}_index_{message_thread_id}"
        async with self.redis.client() as client:
            user_ids = await client.hkeys(index_key)
            return int(user_ids[0]) if user_ids else None

    async def get_user(self, id_: int) -> UserData | None:
        """
        Retrieves user data based on user ID.

        :param id_: The ID of the user.
        :return: The user data or None if not found.
        """
        data = await self._get(self.NAME, id_)
        if data is not None:
            decoded_data = json.loads(data)
            return UserData(**decoded_data)
        return None

    async def update_user(self, id_: int, data: UserData) -> None:
        """
        Updates user data in Redis.

        :param id_: The ID of the user to be updated.
        :param data: The updated user data.
        """
        json_data = json.dumps(data.to_dict())
        await self._set(self.NAME, id_, json_data)
        await self._update_index(data.message_thread_id, id_)

    async def get_all_users_ids(self) -> list[int]:
        """
        Retrieves all user IDs stored in the Redis hash.

        :return: A list of all user IDs.
        """
        async with self.redis.client() as client:
            user_ids = await client.hkeys(self.NAME)
            return [int(user_id) for user_id in user_ids]

    @staticmethod
    def _groq_subject(subject: int | str) -> str:
        """int — Telegram user id; str — identity_id веб-ЛК."""
        if isinstance(subject, str):
            return f"web:{subject}"
        return str(subject)

    def _groq_ctx_key(self, subject: int | str) -> str:
        return f"{self.GROQ_CTX_PREFIX}:{self._groq_subject(subject)}"

    def _groq_op_key(self, subject: int | str) -> str:
        return f"{self.GROQ_OP_PREFIX}:{self._groq_subject(subject)}"

    async def groq_mark_operator_engaged(self, subject: int | str) -> None:
        """
        Оператор написал в топике — ИИ не отвечает в ЛС до истечения TTL (тот же топик,
        затем ИИ снова может отвечать на новые сообщения пользователя).
        """
        key = self._groq_op_key(subject)
        async with self.redis.client() as client:
            await client.set(key, "1", ex=self._groq_operator_lock_sec)

    async def groq_is_operator_engaged(self, subject: int | str) -> bool:
        """True, пока активен ключ после последнего сообщения оператора (см. groq_mark_operator_engaged)."""
        key = self._groq_op_key(subject)
        async with self.redis.client() as client:
            return bool(await client.get(key))

    async def groq_append_turn(self, subject: int | str, role: str, content: str) -> None:
        """
        Добавляет реплику в историю для Groq (порядок хронологический).
        role: "user" | "assistant" (assistant = ответ ИИ или оператора в топике).
        """
        text = (content or "").strip()
        if not text:
            return
        if len(text) > 12000:
            text = text[:12000] + "…"
        if role not in ("user", "assistant"):
            role = "user"
        payload = json.dumps({"role": role, "content": text}, ensure_ascii=False)
        key = self._groq_ctx_key(subject)
        async with self.redis.client() as client:
            await client.rpush(key, payload)
            await client.ltrim(key, -self.GROQ_CTX_MAX_ITEMS, -1)
            await client.expire(key, self.GROQ_CTX_TTL_SEC)

    async def groq_get_history(self, subject: int | str) -> list[dict]:
        """Сообщения для chat completions (без текущего запроса пользователя)."""
        key = self._groq_ctx_key(subject)
        async with self.redis.client() as client:
            raw = await client.lrange(key, 0, -1)
        out: list[dict] = []
        for item in raw:
            try:
                obj = json.loads(item)
                if isinstance(obj, dict) and obj.get("content") and obj.get("role") in (
                    "user",
                    "assistant",
                ):
                    out.append({"role": obj["role"], "content": str(obj["content"])})
            except (json.JSONDecodeError, TypeError, KeyError):
                continue
        return out

    # ── Антиспам: скользящее окно ─────────────────────────────────────────────

    def _spam_key(self, user_id: int) -> str:
        return f"{self.SPAM_PREFIX}:{user_id}"

    async def spam_check_and_record(self, user_id: int) -> bool:
        """
        Возвращает True, если сообщение разрешено (в рамках лимита).
        Возвращает False, если пользователь превысил лимит в текущем окне.
        Использует sliding window на Redis sorted set (score = timestamp).
        """
        if self._spam_max <= 0:
            return True

        key = self._spam_key(user_id)
        now = time.time()
        window_start = now - self._spam_window

        async with self.redis.client() as client:
            pipe = client.pipeline()
            # удаляем устаревшие метки
            pipe.zremrangebyscore(key, "-inf", window_start)
            # считаем оставшиеся
            pipe.zcard(key)
            results = await pipe.execute()

        count = results[1]
        if count >= self._spam_max:
            return False

        async with self.redis.client() as client:
            pipe = client.pipeline()
            pipe.zadd(key, {str(now): now})
            pipe.expire(key, self._spam_window + 1)
            await pipe.execute()

        return True

    async def spam_remaining_wait(self, user_id: int) -> int:
        """
        Сколько секунд осталось до сброса окна (для текста предупреждения).
        """
        key = self._spam_key(user_id)
        now = time.time()
        window_start = now - self._spam_window

        async with self.redis.client() as client:
            oldest = await client.zrangebyscore(
                key, window_start, "+inf", start=0, num=1, withscores=True,
            )

        if not oldest:
            return 0
        oldest_ts = oldest[0][1]
        wait = int(self._spam_window - (now - oldest_ts)) + 1
        return max(0, wait)

    # ── Groq cooldown ─────────────────────────────────────────────────────────

    def _groq_cd_key(self, subject: int | str) -> str:
        return f"{self.GROQ_CD_PREFIX}:{self._groq_subject(subject)}"

    async def groq_cooldown_ok(self, subject: int | str) -> bool:
        """
        True — ИИ может ответить (cooldown истёк или не задан).
        False — ещё рано, пользователь получил ответ ИИ недавно.
        """
        if self._groq_cooldown <= 0:
            return True
        key = self._groq_cd_key(subject)
        async with self.redis.client() as client:
            return not bool(await client.get(key))

    async def groq_cooldown_set(self, subject: int | str) -> None:
        """Ставим cooldown-ключ после ответа ИИ."""
        if self._groq_cooldown <= 0:
            return
        key = self._groq_cd_key(subject)
        async with self.redis.client() as client:
            await client.set(key, "1", ex=self._groq_cooldown)

    # ── Веб-ЛК: сессии и сообщения ────────────────────────────────────────────

    def _web_msg_key(self, identity_id: str) -> str:
        return f"{self.WEB_MSG_PREFIX}:{identity_id}"

    def _web_spam_key(self, identity_id: str) -> str:
        return f"{self.SPAM_PREFIX}:web:{identity_id}"

    async def _update_web_index(self, message_thread_id: int, identity_id: str) -> None:
        index_key = f"{self.WEB_NAME}_index_{message_thread_id}"
        await self._set(index_key, identity_id, "1")

    async def get_web_session(self, identity_id: str) -> WebSessionData | None:
        data = await self._get(self.WEB_NAME, identity_id)
        if data is None:
            return None
        return WebSessionData(**json.loads(data))

    async def update_web_session(self, data: WebSessionData) -> None:
        json_data = json.dumps(data.to_dict())
        await self._set(self.WEB_NAME, data.identity_id, json_data)
        if data.message_thread_id is not None:
            await self._update_web_index(data.message_thread_id, data.identity_id)

    async def get_web_by_message_thread_id(self, message_thread_id: int) -> WebSessionData | None:
        index_key = f"{self.WEB_NAME}_index_{message_thread_id}"
        async with self.redis.client() as client:
            identity_ids = await client.hkeys(index_key)
        if not identity_ids:
            return None
        identity_id = identity_ids[0]
        if isinstance(identity_id, bytes):
            identity_id = identity_id.decode()
        return await self.get_web_session(str(identity_id))

    async def web_spam_check_and_record(self, identity_id: str) -> bool:
        if self._spam_max <= 0:
            return True
        key = self._web_spam_key(identity_id)
        now = time.time()
        window_start = now - self._spam_window
        async with self.redis.client() as client:
            pipe = client.pipeline()
            pipe.zremrangebyscore(key, "-inf", window_start)
            pipe.zcard(key)
            results = await pipe.execute()
        if results[1] >= self._spam_max:
            return False
        async with self.redis.client() as client:
            pipe = client.pipeline()
            pipe.zadd(key, {str(now): now})
            pipe.expire(key, self._spam_window + 1)
            await pipe.execute()
        return True

    async def web_spam_remaining_wait(self, identity_id: str) -> int:
        key = self._web_spam_key(identity_id)
        now = time.time()
        window_start = now - self._spam_window
        async with self.redis.client() as client:
            oldest = await client.zrangebyscore(
                key, window_start, "+inf", start=0, num=1, withscores=True,
            )
        if not oldest:
            return 0
        oldest_ts = oldest[0][1]
        wait = int(self._spam_window - (now - oldest_ts)) + 1
        return max(0, wait)

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone(timedelta(hours=3))).isoformat()

    async def web_append_message(
        self,
        identity_id: str,
        role: str,
        text: str,
        *,
        image_url: str | None = None,
        message_id: str | None = None,
    ) -> WebChatMessage:
        body = (text or "").strip()
        if not body and not image_url:
            raise ValueError("empty message")
        if role not in ("user", "staff", "ai"):
            role = "user"
        msg = WebChatMessage(
            id=message_id or uuid.uuid4().hex,
            role=role,
            text=body[:8000],
            created_at=self._now_iso(),
            image_url=image_url,
        )
        payload = json.dumps(msg.to_dict(), ensure_ascii=False)
        key = self._web_msg_key(identity_id)
        async with self.redis.client() as client:
            await client.rpush(key, payload)
            await client.ltrim(key, -self.WEB_MSG_MAX_ITEMS, -1)
            await client.expire(key, self.WEB_MSG_TTL_SEC)
        return msg

    async def web_get_message(
        self,
        identity_id: str,
        message_id: str,
    ) -> WebChatMessage | None:
        messages = await self.web_list_messages(identity_id)
        for msg in messages:
            if msg.id == message_id:
                return msg
        return None

    async def web_list_messages(
        self,
        identity_id: str,
        since: str | None = None,
    ) -> list[WebChatMessage]:
        key = self._web_msg_key(identity_id)
        async with self.redis.client() as client:
            raw = await client.lrange(key, 0, -1)
        out: list[WebChatMessage] = []
        for item in raw:
            try:
                obj = json.loads(item)
                msg = WebChatMessage(**obj)
            except (json.JSONDecodeError, TypeError, KeyError):
                continue
            if since and msg.created_at <= since:
                continue
            out.append(msg)
        return out
