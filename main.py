import asyncio
import logging
import os
from pathlib import Path

from aiohttp import web
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from handlers.forwarded_messages import router as forwarded_messages_router
from core.event_reporter import emit, start_reporter_from_env, stop_reporter
from core.json_db import JsonDB
from handlers.webhook import sonarr_webhook_handler
from handlers.commands import router as commands_router
from handlers.callbacks import router as callbacks_router
from services.telegram.user_client import TelegramUserClient
from services.telegram.release_monitor import ReleaseMonitor
from services.dub_detector import DubDetector

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "0.0.0.0")
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", "8081"))
SONARR_WEBHOOK_PATH = os.getenv("SONARR_WEBHOOK_PATH", "/sonarr")
DATABASE_PATH = os.getenv("DATABASE_PATH", "data/database.json")
DUB_DETECTOR_INTERVAL = int(os.getenv("DUB_DETECTOR_INTERVAL", "900"))
NYAA_RSS_URL = "https://nyaa.si/?page=rss&c=0_0&q=%5BToonsHub%5D+dual"
STATE_PATH = Path("data/dub_detector_state.json")

RELEASE_SOURCE_CHANNEL = [
    "@ridnyiholos",
    "@Shrbq",
]

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is missing from .env")

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

dp = Dispatcher(storage=MemoryStorage())
dp.include_router(commands_router)
dp.include_router(callbacks_router)
dp.include_router(forwarded_messages_router)

db = JsonDB(DATABASE_PATH)


async def start_release_monitor(app: web.Application) -> None:
    try:
        user_client = TelegramUserClient.from_env()
        release_monitor = ReleaseMonitor(
            user_client=user_client,
            db=app["db"],
            bot=app["bot"],
            source_channel=RELEASE_SOURCE_CHANNEL,
            notify_chat_id=TELEGRAM_CHAT_ID,
        )

        await release_monitor.start()

        app["tg_user_client"] = user_client
        app["release_monitor"] = release_monitor
        logger.info("Release monitor started for %s", RELEASE_SOURCE_CHANNEL)
        emit(
            category="system",
            event="service_started",
            message=f"Release monitor started for {RELEASE_SOURCE_CHANNEL}",
            source=__name__,
            data={"source_channel": RELEASE_SOURCE_CHANNEL},
        )

    except Exception as e:
        logger.exception("Failed to start release monitor: %s", e)
        emit(
            category="system",
            event="service_failed",
            message=f"Failed to start release monitor: {e}",
            level="error",
            source=__name__,
        )
        app["tg_user_client"] = None
        app["release_monitor"] = None


async def stop_release_monitor(app: web.Application) -> None:
    release_monitor = app.get("release_monitor")
    user_client = app.get("tg_user_client")

    if release_monitor:
        await release_monitor.stop()

    if user_client:
        await user_client.stop()


async def dub_detector_loop(app: web.Application) -> None:
    detector = app["dub_detector"]
    interval = app["dub_detector_interval"]

    while True:
        try:
            await detector.check_once()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("Dub detector check failed: %s", e)
            emit(
                category="dub_detector",
                event="feed_error",
                message=f"Dub detector check failed: {e}",
                level="error",
                source=__name__,
            )

        await asyncio.sleep(interval)


async def start_dub_detector(app: web.Application) -> None:
    try:
        detector = DubDetector(
            bot=app["bot"],
            notify_chat_id=TELEGRAM_CHAT_ID,
            db=app["db"],
            rss_url=NYAA_RSS_URL,
            state_path=STATE_PATH,
        )
        app["dub_detector"] = detector
        app["dub_detector_interval"] = DUB_DETECTOR_INTERVAL
        app["dub_detector_task"] = asyncio.create_task(dub_detector_loop(app))
        logger.info("Dub detector started with interval %ss", DUB_DETECTOR_INTERVAL)
        emit(
            category="dub_detector",
            event="service_started",
            message=f"Dub detector started with interval {DUB_DETECTOR_INTERVAL}s",
            source=__name__,
            data={"interval": DUB_DETECTOR_INTERVAL},
        )
    except Exception as e:
        logger.exception("Failed to start dub detector: %s", e)
        emit(
            category="dub_detector",
            event="service_failed",
            message=f"Failed to start dub detector: {e}",
            level="error",
            source=__name__,
        )
        app["dub_detector"] = None
        app["dub_detector_task"] = None


async def stop_dub_detector(app: web.Application) -> None:
    task = app.get("dub_detector_task")
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def start_web_server() -> web.AppRunner:
    app = web.Application()

    app["bot"] = bot
    app["db"] = db

    app.router.add_post(SONARR_WEBHOOK_PATH, sonarr_webhook_handler)

    app.on_startup.append(start_release_monitor)
    app.on_startup.append(start_dub_detector)
    app.on_cleanup.append(stop_dub_detector)
    app.on_cleanup.append(stop_release_monitor)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, WEBHOOK_HOST, WEBHOOK_PORT)
    await site.start()

    webhook_url = f"http://{WEBHOOK_HOST}:{WEBHOOK_PORT}{SONARR_WEBHOOK_PATH}"
    logger.info("Webhook server started: %s", webhook_url)
    emit(
        category="system",
        event="service_started",
        message=f"Webhook server started: {webhook_url}",
        source=__name__,
    )
    return runner


async def main():
    db.ensure_exists()
    await start_reporter_from_env()
    runner = await start_web_server()

    try:
        logger.info("Starting Telegram bot polling...")
        emit(
            category="bot",
            event="service_started",
            message="Starting Telegram bot polling",
            source=__name__,
        )
        await dp.start_polling(bot)
    finally:
        await runner.cleanup()
        await bot.session.close()
        emit(
            category="system",
            event="service_stopped",
            message="Bot stopped",
            source=__name__,
        )
        await stop_reporter()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
