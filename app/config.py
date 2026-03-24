from dataclasses import dataclass

from environs import Env


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
    """
    TOKEN: str
    DEV_ID: int
    GROUP_ID: int
    BOT_EMOJI_ID: str


@dataclass
class GroqConfig:
    """Опциональная интеграция Groq (OpenAI-совместимый API)."""
    API_KEY: str
    MODEL: str

    @property
    def enabled(self) -> bool:
        return bool(self.API_KEY and self.API_KEY.strip())


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
    """
    bot: BotConfig
    redis: RedisConfig
    groq: GroqConfig


def load_config() -> Config:
    """
    Load the configuration from environment variables and return a Config object.

    :return: The Config object with loaded configuration.
    """
    env = Env()
    env.read_env()

    return Config(
        bot=BotConfig(
            TOKEN=env.str("BOT_TOKEN"),
            DEV_ID=env.int("BOT_DEV_ID"),
            GROUP_ID=env.int("BOT_GROUP_ID"),
            BOT_EMOJI_ID=env.str("BOT_EMOJI_ID"),
        ),
        redis=RedisConfig(
            HOST=env.str("REDIS_HOST"),
            PORT=env.int("REDIS_PORT"),
            DB=env.int("REDIS_DB"),
        ),
        groq=GroqConfig(
            API_KEY=_strip_env_secret(env.str("GROQ_API_KEY", default="")),
            MODEL=env.str("GROQ_MODEL", default="llama-3.1-8b-instant").strip(),
        ),
    )
