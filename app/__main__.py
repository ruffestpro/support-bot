import asyncio
import contextlib
import logging
import warnings

# APScheduler 3.10 тянет pkg_resources; setuptools выдаёт UserWarning при импорте — не мы.
warnings.filterwarnings(
    "ignore",
    message=r"pkg_resources is deprecated as an API",
    category=UserWarning,
)

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from apscheduler.jobstores.redis import RedisJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from uvicorn import Config as UvicornConfig
from uvicorn import Server as UvicornServer

from .bot import commands
from .bot.handlers import include_routers
from .bot.middlewares import register_middlewares
from .bot.utils.redis import RedisStorage
from .config import load_config, Config
from .logger import setup_logger
from .web import create_web_app

_log = logging.getLogger(__name__)


async def on_shutdown(
    apscheduler: AsyncIOScheduler,
    dispatcher: Dispatcher,
    config: Config,
    bot: Bot,
    web_server: UvicornServer | None = None,
) -> None:
    """
    Shutdown event handler. This runs when the bot shuts down.

    :param apscheduler: AsyncIOScheduler: The apscheduler instance.
    :param dispatcher: Dispatcher: The bot dispatcher.
    :param config: Config: The config instance.
    :param bot: Bot: The bot instance.
    """
    if web_server is not None:
        web_server.should_exit = True
    # Stop apscheduler
    apscheduler.shutdown()
    # Delete commands and close storage when shutting down
    await commands.delete(bot, config)
    await dispatcher.storage.close()
    await bot.delete_webhook()
    await bot.session.close()


async def on_startup(
    apscheduler: AsyncIOScheduler,
    config: Config,
    bot: Bot,
) -> None:
    """
    Startup event handler. This runs when the bot starts up.

    :param apscheduler: AsyncIOScheduler: The apscheduler instance.
    :param config: Config: The config instance.
    :param bot: Bot: The bot instance.
    """
    # Start apscheduler
    apscheduler.start()
    # Setup commands when starting up
    await commands.setup(bot, config)

    if config.groq.enabled:
        if not config.groq.API_KEY.startswith("gsk_"):
            _log.warning(
                "Groq: ключ не начинается с gsk_ — проверь GROQ_API_KEY (кавычки, пробелы, не тот токен)."
            )
        _log.info("Groq: включён, модель %s", config.groq.MODEL)
    elif not config.groq.ENABLED:
        _log.info("Groq: выключен (GROQ_ENABLED=false)")


def _create_web_server(
    bot: Bot,
    config: Config,
    redis_storage: RedisStorage,
) -> UvicornServer | None:
    if not config.web.ENABLED:
        _log.info("Web API: выключен (WEB_API_ENABLED=false)")
        return None

    if not config.web.CABINET_API_URL:
        _log.warning(
            "Web API: CABINET_API_URL не задан — HTTP API не запускается",
        )
        return None

    web_app = create_web_app(bot, config, redis_storage)
    uvicorn_config = UvicornConfig(
        web_app,
        host=config.web.HOST,
        port=config.web.PORT,
        log_level="info",
        loop="asyncio",
    )
    server = UvicornServer(uvicorn_config)
    _log.info(
        "Web API: слушает %s:%s (CABINET_API_URL=%s)",
        config.web.HOST,
        config.web.PORT,
        config.web.CABINET_API_URL,
    )
    return server


async def main() -> None:
    """
    Main function that initializes the bot and starts the event loop.
    """
    # Load config
    config = load_config()

    # Initialize apscheduler
    job_store = RedisJobStore(
        host=config.redis.HOST,
        port=config.redis.PORT,
        db=config.redis.DB,
    )
    apscheduler = AsyncIOScheduler(
        jobstores={"default": job_store},
    )

    # Initialize Redis storage
    storage = RedisStorage.from_url(
        url=config.redis.dsn(),
    )

    # Create Bot and Dispatcher instances
    bot = Bot(
        token=config.bot.TOKEN,
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML,
        ),
    )
    redis_storage = RedisStorage(
        storage.redis,
        groq_operator_lock_sec=config.groq.OPERATOR_LOCK_SEC,
        spam_max_messages=config.antispam.MAX_MESSAGES,
        spam_window_sec=config.antispam.WINDOW_SEC,
        groq_cooldown_sec=config.antispam.GROQ_COOLDOWN_SEC,
    )

    dp = Dispatcher(
        apscheduler=apscheduler,
        storage=storage,
        config=config,
        bot=bot,
    )

    web_server = _create_web_server(bot, config, redis_storage)

    async def _shutdown_wrapper() -> None:
        await on_shutdown(apscheduler, dp, config, bot, web_server)

    dp.startup.register(on_startup)
    dp.shutdown.register(_shutdown_wrapper)

    include_routers(dp)
    register_middlewares(
        dp, config=config, redis=storage.redis, apscheduler=apscheduler
    )

    await bot.delete_webhook()

    tasks: list[asyncio.Task] = [
        asyncio.create_task(
            dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types()),
        ),
    ]
    if web_server is not None:
        tasks.append(asyncio.create_task(web_server.serve()))

    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task


if __name__ == "__main__":
    # Set up logging
    setup_logger()
    # Run the bot
    asyncio.run(main())
