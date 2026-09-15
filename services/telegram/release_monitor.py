import logging
from datetime import timezone

from telethon import events

from services.telegram.downloader import TelegramDownloader
from utils.text_parser import (
    extract_episode_code,
    extract_normalized_show_title,
    extract_show_romaji_name,
    extract_telegram_message_link,
    has_mvo_release_tag,
)

logger = logging.getLogger(__name__)


class ReleaseMonitor:
    def __init__(
        self,
        user_client,
        db,
        bot,
        source_channel,
        notify_chat_id,
        downloader=None,
    ):
        self.user_client = user_client
        self.db = db
        self.bot = bot
        self.source_channel = source_channel
        self.notify_chat_id = int(notify_chat_id) if notify_chat_id else None
        self.downloader = downloader or TelegramDownloader()

        self.client = user_client.get_client()
        self._handler = None
        self._started = False

    async def start(self) -> None:
        if self._started:
            logger.warning("[RELEASE MONITOR] start() called but already started")
            return

        await self.user_client.start()

        async def _handler(event):
            try:
                await self._handle_message(event)
            except Exception:
                logger.exception("[RELEASE MONITOR] error in _handle_message")

        self._handler = _handler

        logger.info(
            "[RELEASE MONITOR] registering NewMessage handler for chats=%s",
            self.source_channel,
        )

        self.client.add_event_handler(
            self._handler,
            events.NewMessage(chats=self.source_channel),
        )

        self._started = True
        logger.info("[RELEASE MONITOR] listening to %s", self.source_channel)

    async def stop(self) -> None:
        if not self._started:
            return

        if self._handler is not None:
            self.client.remove_event_handler(self._handler)
            self._handler = None

        self._started = False
        logger.info("[RELEASE MONITOR] stopped")

    async def _handle_message(self, event) -> None:
        # Basic debug info for every message that reaches this handler
        chat_id = getattr(event.chat, "id", None)
        msg_id = event.message.id
        text = event.text or ""

        logger.info(
            "[RELEASE MONITOR] NEW MESSAGE IN CHANNEL: "
            "chat_id=%s, message_id=%s, text_preview=%s",
            chat_id,
            msg_id,
            (text[:80].replace("\n", " ") if text else "(empty)"),
        )

        if not text:
            logger.info(
                "[RELEASE MONITOR] SKIP: message has no text, message_id=%s",
                msg_id,
            )
            return

        if not has_mvo_release_tag(text):
            logger.info(
                "[RELEASE MONITOR] SKIP: no MVO tag, message_id=%s, text_preview=%s",
                msg_id,
                text[:80].replace("\n", " "),
            )
            return

        normalized_title = extract_normalized_show_title(text)
        romaji_title = extract_show_romaji_name(text)

        logger.info(
            "[RELEASE MONITOR] MVO post detected: "
            "normalized_title=%s, romaji_title=%s, message_id=%s",
            normalized_title,
            romaji_title,
            msg_id,
        )

        if not normalized_title:
            logger.info(
                "[RELEASE MONITOR] SKIP: MVO post without show tag, message_id=%s",
                msg_id,
            )
            return

        show = self.db.find_show_by_normalized_title(normalized_title)
        if not show:
            logger.info(
                "[RELEASE MONITOR] SKIP: no DB match for '%s', message_id=%s",
                normalized_title,
                msg_id,
            )
            return

        preference = (show.get("preference") or "").strip().lower()
        if preference != "mvo":
            logger.info(
                "[RELEASE MONITOR] SKIP: DB match for '%s' ignored, "
                "preference is '%s', expected 'mvo', message_id=%s",
                normalized_title,
                preference,
                msg_id,
            )
            return

        episode_code = extract_episode_code(text)
        tg_link = extract_telegram_message_link(text)
        if tg_link:
            tg_link = tg_link.replace("https://https://", "https://")
            tg_link = tg_link.replace("http://http://", "http://")

        show_title = show.get("title", normalized_title)
        download_name = romaji_title or normalized_title

        message_dt = event.message.date
        if message_dt is not None:
            if message_dt.tzinfo is None:
                message_dt = message_dt.replace(tzinfo=timezone.utc)
            message_time = message_dt.astimezone().isoformat()
        else:
            message_time = None

        updated = False
        if episode_code and message_time:
            updated = self.db.update_last_download(
                normalized_title=normalized_title,
                episode=episode_code,
                download_time=message_time,
            )

        logger.info(
            "[RELEASE MONITOR] MATCH\n"
            "  show: %s\n"
            "  normalized_title: %s\n"
            "  romaji_title: %s\n"
            "  episode: %s\n"
            "  post_time: %s\n"
            "  link: %s\n"
            "  source_message_id: %s\n"
            "  db_updated: %s",
            show_title,
            normalized_title,
            download_name,
            episode_code or "unknown",
            message_time or "unknown",
            tg_link or "not found",
            msg_id,
            updated,
        )

        status_message = await self._notify_match(show_title, episode_code)
        await self._try_download(
            source_message=event.message,
            show_title=show_title,
            romaji_title=download_name,
            episode_code=episode_code,
            tg_link=tg_link,
            status_message=status_message,
        )

    async def _notify_match(
        self,
        show_title: str,
        episode_code: str | None,
    ):
        if not self.notify_chat_id:
            return None

        text = (
            "Release matched\n"
            f"{show_title} - {episode_code or 'Unknown'} - Download Started"
        )

        try:
            return await self.bot.send_message(
                chat_id=self.notify_chat_id,
                text=text,
            )
        except Exception as e:
            logger.exception("[RELEASE MONITOR] failed to send bot notification: %s", e)
            return None

    async def _try_download(
        self,
        source_message,
        show_title: str,
        romaji_title: str,
        episode_code: str | None,
        tg_link: str | None,
        status_message=None,
    ) -> None:
        final_text = None

        try:
            if tg_link:
                downloaded_path = await self.downloader.download_from_link(
                    client=self.client,
                    link=tg_link,
                    romaji_title=romaji_title,
                    episode_code=episode_code,
                )
            else:
                downloaded_path = await self.downloader.download_from_message(
                    message=source_message,
                    romaji_title=romaji_title,
                    episode_code=episode_code,
                )

            if downloaded_path:
                final_text = (
                    "Release matched\n"
                    f"{show_title} - {episode_code or 'Unknown'} - Download Finished"
                )
            else:
                final_text = (
                    "Release matched\n"
                    f"{show_title} - {episode_code or 'Unknown'} - Download Failed"
                )
        except Exception as e:
            logger.exception("[RELEASE MONITOR] download failed: %s", e)
            final_text = (
                "Release matched\n"
                f"{show_title} - {episode_code or 'Unknown'} - Download Failed"
            )

        if status_message and self.notify_chat_id:
            try:
                await self.bot.edit_message_text(
                    chat_id=self.notify_chat_id,
                    message_id=status_message.message_id,
                    text=final_text,
                )
                return
            except Exception as e:
                logger.exception("[RELEASE MONITOR] failed to edit status message: %s", e)

        if self.notify_chat_id and final_text:
            try:
                await self.bot.send_message(
                    chat_id=self.notify_chat_id,
                    text=final_text,
                )
            except Exception as e:
                logger.exception("[RELEASE MONITOR] failed to send fallback status message: %s", e)