# Anime release tracker bot

A small Telegram bot for tracking anime releases, managing a local show list, monitoring matched release posts, and receiving Sonarr webhook events. The project combines aiogram for the bot, Telethon for channel monitoring, and a JSON file for persistence.[1][2]

## What it does

- Shows a weekly schedule based on `last_download_time` plus 7 days.
- Lets you manage a tracked show list from Telegram.
- Monitors configured Telegram channels for MVO release posts and matches them against the DB.
- Updates matched shows with `last_downloaded_episode` and `last_download_time` using the Telegram post timestamp.
- Accepts Sonarr webhook events.
- Can add a new show from a forwarded release post by parsing the Ukrainian title, romaji-based normalized title, episode code, and timestamp.[3][4]

## Main pieces

- `main.py` — starts aiogram polling, aiohttp webhook server, and Telethon release monitor.
- `core/json_db.py` — JSON-backed storage for tracked and discovered shows.
- `handlers/commands.py` — bot commands such as schedule, today, tomorrow, discovered, and manage.
- `handlers/callbacks.py` — inline button actions for list management and add-show flows.
- `handlers/forwarded_messages.py` — parses forwarded release posts and prepares add-show confirmation.
- `handlers/webhook.py` — Sonarr webhook entrypoint.
- `services/telegram/release_monitor.py` — background listener for release posts.
- `utils/text_parser.py` — parsing helpers for hashtags, titles, episode codes, and Telegram links.

## Data model

Tracked shows are stored in `data/database.json`. A show record commonly includes:

- `title`
- `normalized_title`
- `preference`
- `last_downloaded_episode`
- `last_download_time`

`normalized_title` is used as the unique key for matching and duplicate prevention.

## How matching works

For Telegram release posts:

- Ukrainian display title is parsed from the start of the message before the first `[` block.
- Romaji title is parsed from the non-Cyrillic `_MVO` hashtag.
- `normalized_title` is generated from the romaji title.
- `episode_code` is parsed from patterns like `[03 з XX]` and converted to `S01E03`.
- On DB match, the release monitor updates the show and sends a bot notification.[5][6]

## Environment variables

Typical `.env` values:

- `BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `WEBHOOK_HOST`
- `WEBHOOK_PORT`
- `SONARR_WEBHOOK_PATH`
- `DATABASE_PATH`
- Telethon user client credentials used by `TelegramUserClient.from_env()`

## Run

1. Install dependencies.
2. Create `.env` with bot token, chat ID, webhook settings, DB path, and Telethon credentials.
3. Start the app with `python main.py`.
4. Open the bot and use `/manage`, `/schedule`, or forward a release post for manual add.

## Notes

- The bot uses aiogram FSM for multi-step add flows and confirmations.[3]
- Forwarded-message add is intended as a manual fallback when a show is not yet in the DB.[4]
- Release monitoring and bot polling run in the same async application.[2]
