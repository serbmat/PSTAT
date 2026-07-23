from datetime import timezone

from telethon import events

from utils.text_parser import (
    extract_episode_code,
    extract_normalized_show_title,
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
    ):
        self.user_client = user_client
        self.db = db
        self.bot = bot
        self.source_channel = source_channel
        self.notify_chat_id = int(notify_chat_id) if notify_chat_id else None

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

        episode_code = extract_episode_code(text)
        tg_link = extract_telegram_message_link(text)
        show_title = show.get("title", normalized_title)

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
            f"  episode: {episode_code or 'unknown'}\n"
            f"  post_time: {message_time or 'unknown'}\n"
            f"  link: {tg_link or 'not found'}\n"
            f"  source_message_id: {event.id}\n"
            f"  db_updated: {updated}"
        )

        if self.notify_chat_id:
            lines = [
                "🔔 <b>Release matched</b>",
                f"Show: <b>{show_title}</b>",
                f"Episode: <b>{episode_code or 'unknown'}</b>",
                f"Updated DB: <b>{'yes' if updated else 'no'}</b>",
            ]

            if tg_link:
                lines.append(f"Link: {tg_link}")

            try:
                await self.bot.send_message(
                    chat_id=self.notify_chat_id,
                    text="\n".join(lines),
                )
            except Exception as e:
                print(f"[RELEASE MONITOR] failed to send bot notification: {e}")