from dataclasses import dataclass

from environs import Env


def _normalize_bot_username(value: str) -> str:
    """Имя бота для t.me без @."""
    return (value or "").strip().lstrip("@")


def _strip_env_secret(value: str) -> str:
    """Убирает пробелы и обрамляющие кавычки из секретов из .env / Docker env."""
    v = (value or "").strip()
    if len(v) >= 2 and v[0] in "\"'" and v[0] == v[-1]:
        v = v[1:-1].strip()
    return v


@dataclass
class BotConfig:
    """
    Data class representing the configuration for the bot.

    Attributes:
    - TOKEN (str): The bot token.
    - DEV_ID (int): The developer's user ID.
    - GROUP_ID (int): The group chat ID.
    - BOT_EMOJI_ID (str): The custom emoji ID for the group's topic.
    - BOT_USERNAME (str): Юзернейм основного бота (без @) для deep link из /information.
    """
    TOKEN: str
    DEV_ID: int
    GROUP_ID: int
    BOT_EMOJI_ID: str
    BOT_USERNAME: str


@dataclass
class AntiSpamConfig:
    """Настройки антиспама для приватных сообщений."""
    # Скользящее окно: не более MAX_MESSAGES сообщений за WINDOW_SEC секунд
    MAX_MESSAGES: int
    WINDOW_SEC: int
    # Cooldown между ответами ИИ (0 = без ограничения)
    GROQ_COOLDOWN_SEC: int


@dataclass
class GroqConfig:
    """Опциональная интеграция Groq (OpenAI-совместимый API)."""
    API_KEY: str
    MODEL: str
    # Мастер-выключатель: GROQ_ENABLED=false — не вызывать ИИ даже при наличии ключа
    ENABLED: bool
    # После сообщения оператора в топике ИИ молчит столько секунд; затем снова может отвечать в том же топике
    OPERATOR_LOCK_SEC: int
    # Vision: фото + подпись — отдельная модель с поддержкой изображений
    VISION_MODEL: str
    VISION_ENABLED: bool

    @property
    def enabled(self) -> bool:
        return self.ENABLED and bool(self.API_KEY and self.API_KEY.strip())

    @property
    def vision_enabled(self) -> bool:
        return self.enabled and self.VISION_ENABLED and bool(self.VISION_MODEL)


@dataclass
class RedisConfig:
    """
    Data class representing the configuration for Redis.

    Attributes:
    - HOST (str): The Redis host.
    - PORT (int): The Redis port.
    - DB (int): The Redis database number.
    """
    HOST: str
    PORT: int
    DB: int

    def dsn(self) -> str:
        """
        Generates a Redis connection DSN (Data Source Name) using the provided host, port, and database.

        :return: The generated DSN.
        """
        return f"redis://{self.HOST}:{self.PORT}/{self.DB}"


@dataclass
class Config:
    """
    Data class representing the overall configuration for the application.

    Attributes:
    - bot (BotConfig): The bot configuration.
    - redis (RedisConfig): The Redis configuration.
    - groq (GroqConfig): Groq LLM (пустой ключ = выключено).
    - antispam (AntiSpamConfig): Настройки антиспама.
    """
    bot: BotConfig
    redis: RedisConfig
    groq: GroqConfig
    antispam: AntiSpamConfig


def load_config() -> Config:
    """
    Load the configuration from environment variables and return a Config object.

    :return: The Config object with loaded configuration.
    """
    env = Env()
    env.read_env()

    return Config(
        antispam=AntiSpamConfig(
            MAX_MESSAGES=max(1, env.int("ANTISPAM_MAX_MESSAGES", default=5)),
            WINDOW_SEC=max(5, env.int("ANTISPAM_WINDOW_SEC", default=30)),
            GROQ_COOLDOWN_SEC=max(0, env.int("ANTISPAM_GROQ_COOLDOWN_SEC", default=10)),
        ),
        bot=BotConfig(
            TOKEN=env.str("BOT_TOKEN"),
            DEV_ID=env.int("BOT_DEV_ID"),
            GROUP_ID=env.int("BOT_GROUP_ID"),
            BOT_EMOJI_ID=env.str("BOT_EMOJI_ID"),
            BOT_USERNAME=_normalize_bot_username(env.str("BOT_USERNAME", default="")),
        ),
        redis=RedisConfig(
            HOST=env.str("REDIS_HOST"),
            PORT=env.int("REDIS_PORT"),
            DB=env.int("REDIS_DB"),
        ),
        groq=GroqConfig(
            API_KEY=_strip_env_secret(env.str("GROQ_API_KEY", default="")),
            MODEL=env.str("GROQ_MODEL", default="llama-3.1-8b-instant").strip(),
            ENABLED=env.bool("GROQ_ENABLED", default=True),
            OPERATOR_LOCK_SEC=max(
                3600,
                env.int("GROQ_OPERATOR_LOCK_SEC", default=3600),
            ),
            VISION_MODEL=env.str(
                "GROQ_VISION_MODEL",
                default="meta-llama/llama-4-scout-17b-16e-instruct",
            ).strip(),
            VISION_ENABLED=env.bool("GROQ_VISION_ENABLED", default=False),
        ),
    )
