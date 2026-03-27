import json

from redis.asyncio import Redis

from .models import UserData


GROQ_OPERATOR_CONTENT_PREFIX = "[Поддержка (оператор)]"


class RedisStorage:
    """Class for managing user data storage using Redis."""

    NAME = "users"
    GROQ_CTX_PREFIX = "groq_ctx"
    GROQ_OP_PREFIX = "groq_op"
    GROQ_CTX_MAX_ITEMS = 48
    GROQ_CTX_TTL_SEC = 60 * 60 * 24 * 14

    def __init__(self, redis: Redis, groq_operator_lock_sec: int = 3600) -> None:
        """
        Initializes the RedisStorage instance.

        :param redis: The Redis instance to be used for data storage.
        :param groq_operator_lock_sec: TTL ключа блокировки ИИ после сообщения оператора.
        """
        self.redis = redis
        self._groq_operator_lock_sec = groq_operator_lock_sec

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

    def _groq_ctx_key(self, user_id: int) -> str:
        return f"{self.GROQ_CTX_PREFIX}:{user_id}"

    def _groq_op_key(self, user_id: int) -> str:
        return f"{self.GROQ_OP_PREFIX}:{user_id}"

    async def groq_mark_operator_engaged(self, user_id: int) -> None:
        """
        Оператор написал в топике — ИИ не отвечает в ЛС до истечения TTL (тот же топик,
        затем ИИ снова может отвечать на новые сообщения пользователя).
        """
        key = self._groq_op_key(user_id)
        async with self.redis.client() as client:
            await client.set(key, "1", ex=self._groq_operator_lock_sec)

    async def groq_is_operator_engaged(self, user_id: int) -> bool:
        """True, пока активен ключ после последнего сообщения оператора (см. groq_mark_operator_engaged)."""
        key = self._groq_op_key(user_id)
        async with self.redis.client() as client:
            return bool(await client.get(key))

    async def groq_append_turn(self, user_id: int, role: str, content: str) -> None:
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
        key = self._groq_ctx_key(user_id)
        async with self.redis.client() as client:
            await client.rpush(key, payload)
            await client.ltrim(key, -self.GROQ_CTX_MAX_ITEMS, -1)
            await client.expire(key, self.GROQ_CTX_TTL_SEC)

    async def groq_get_history(self, user_id: int) -> list[dict]:
        """Сообщения для chat completions (без текущего запроса пользователя)."""
        key = self._groq_ctx_key(user_id)
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
