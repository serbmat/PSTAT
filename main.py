import asyncio
import os

from aiohttp import web
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from handlers.forwarded_messages import router as forwarded_messages_router
from core.json_db import JsonDB
from handlers.webhook import sonarr_webhook_handler
from handlers.commands import router as commands_router
from handlers.callbacks import router as callbacks_router
from services.telegram.user_client import TelegramUserClient
from services.telegram.release_monitor import ReleaseMonitor


load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "0.0.0.0")
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", "8080"))
SONARR_WEBHOOK_PATH = os.getenv("SONARR_WEBHOOK_PATH", "/sonarr")
DATABASE_PATH = os.getenv("DATABASE_PATH", "data/database.json")
# RELEASE_SOURCE_CHANNEL = os.getenv("RELEASE_SOURCE_CHANNEL", "@robotaholosom")
RELEASE_SOURCE_CHANNEL = [
    "@robotaholosom",
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
        print(f"Release monitor started for {RELEASE_SOURCE_CHANNEL}")

    except Exception as e:
        print(f"Failed to start release monitor: {e}")
        app["tg_user_client"] = None
        app["release_monitor"] = None


async def stop_release_monitor(app: web.Application) -> None:
    release_monitor = app.get("release_monitor")
    user_client = app.get("tg_user_client")

    if release_monitor:
        await release_monitor.stop()

    if user_client:
        await user_client.stop()


async def start_web_server() -> web.AppRunner:
    app = web.Application()

    app["bot"] = bot
    app["db"] = db

    app.router.add_post(SONARR_WEBHOOK_PATH, sonarr_webhook_handler)

    app.on_startup.append(start_release_monitor)
    app.on_cleanup.append(stop_release_monitor)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, WEBHOOK_HOST, WEBHOOK_PORT)
    await site.start()

    print(f"Webhook server started: http://{WEBHOOK_HOST}:{WEBHOOK_PORT}{SONARR_WEBHOOK_PATH}")
    return runner


async def main():
    db.ensure_exists()
    runner = await start_web_server()

    try:
        print("Starting Telegram bot polling...")
        await dp.start_polling(bot)
    finally:
        await runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Bot stopped.")