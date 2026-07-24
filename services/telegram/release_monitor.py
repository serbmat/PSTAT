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
            return

        await self.user_client.start()

        async def _handler(event):
            await self._handle_message(event)

        self._handler = _handler
        self.client.add_event_handler(
            self._handler,
            events.NewMessage(chats=self.source_channel),
        )

        self._started = True
        print(f"[RELEASE MONITOR] listening to {self.source_channel}")

    async def stop(self) -> None:
        if not self._started:
            return

        if self._handler is not None:
            self.client.remove_event_handler(self._handler)
            self._handler = None

        self._started = False
        print("[RELEASE MONITOR] stopped")

    async def _handle_message(self, event) -> None:
        text = event.raw_text or ""
        if not text:
            return

        if not has_mvo_release_tag(text):
            return

        normalized_title = extract_normalized_show_title(text)
        romaji_title = extract_show_romaji_name(text)

        print(f"text={text}, \nnormalized title={normalized_title}")

        if not normalized_title:
            print(f"[RELEASE MONITOR] MVO post without show tag, message_id={event.id}")
            return

        show = self.db.find_show_by_normalized_title(normalized_title)
        if not show:
            print(
                f"[RELEASE MONITOR] no DB match for '{normalized_title}', "
                f"message_id={event.id}"
            )
            return

        preference = (show.get("preference") or "").strip().lower()
        if preference != "mvo":
            print(
                f"[RELEASE MONITOR] DB match for '{normalized_title}' ignored, "
                f"preference is '{show.get('preference')}', expected 'mvo', "
                f"message_id={event.id}"
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

        print(
            "[RELEASE MONITOR] MATCH\n"
            f"  show: {show_title}\n"
            f"  normalized_title: {normalized_title}\n"
            f"  romaji_title: {download_name}\n"
            f"  episode: {episode_code or 'unknown'}\n"
            f"  post_time: {message_time or 'unknown'}\n"
            f"  link: {tg_link or 'not found'}\n"
            f"  source_message_id: {event.id}\n"
            f"  db_updated: {updated}"
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
            print(f"[RELEASE MONITOR] failed to send bot notification: {e}")
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
            print(f"[RELEASE MONITOR] download failed: {e}")
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
                print(f"[RELEASE MONITOR] failed to edit status message: {e}")

        if self.notify_chat_id and final_text:
            try:
                await self.bot.send_message(
                    chat_id=self.notify_chat_id,
                    text=final_text,
                )
            except Exception as e:
                print(f"[RELEASE MONITOR] failed to send fallback status message: {e}")