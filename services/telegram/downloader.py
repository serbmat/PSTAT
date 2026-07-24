import re
import time
from pathlib import Path
from typing import Optional


_TG_TOPIC_LINK_RE = re.compile(r"https?://t\.me/([A-Za-z0-9_]+)/(\d+)(?:/(\d+))?")


class TelegramDownloader:
    def __init__(self, download_dir: str = r"D:\Downloads\mmmmmmm"):
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)

    def _safe_name(self, value: str) -> str:
        allowed = []
        for ch in value:
            if ch.isalnum() or ch in (" ", "-", "_", ".", "(", ")"):
                allowed.append(ch)
            else:
                allowed.append("_")
        return "".join(allowed).strip().replace(" ", "_")

    def build_show_dir(self, romaji_title: str) -> Path:
        show_dir = self.download_dir / self._safe_name(romaji_title)
        show_dir.mkdir(parents=True, exist_ok=True)
        return show_dir

    def build_target_path(
        self,
        romaji_title: str,
        episode_code: Optional[str] = None,
    ) -> Path:
        show_dir = self.build_show_dir(romaji_title)

        base_name = self._safe_name(romaji_title)
        if episode_code:
            base_name = f"{base_name}_{episode_code}"

        return show_dir / base_name

    def parse_message_link(self, link: str) -> tuple[str, int, Optional[int]] | None:
        if not link:
            return None

        clean_link = link.strip()
        clean_link = clean_link.replace("https://https://", "https://")
        clean_link = clean_link.replace("http://http://", "http://")

        match = _TG_TOPIC_LINK_RE.search(clean_link)
        if not match:
            return None

        chat_username = match.group(1)
        topic_id = int(match.group(2))
        message_id = int(match.group(3)) if match.group(3) else None
        return chat_username, topic_id, message_id

    async def get_latest_media_message_in_topic(self, client, link: str):
        parsed = self.parse_message_link(link)
        if not parsed:
            return None

        chat_username, topic_id, explicit_message_id = parsed
        entity = await client.get_entity(chat_username)

        if explicit_message_id is not None:
            msg = await client.get_messages(entity, ids=explicit_message_id)
            if msg and getattr(msg, "media", None):
                return msg

        async for msg in client.iter_messages(entity, reply_to=topic_id, limit=20):
            if getattr(msg, "media", None):
                return msg

        return None

    def _make_progress_callback(self, label: str):
        started_at = time.monotonic()
        last_print_at = 0.0

        def callback(current: int, total: int):
            nonlocal last_print_at

            now = time.monotonic()
            if now - last_print_at < 1 and current < total:
                return
            last_print_at = now

            elapsed = max(now - started_at, 0.001)
            speed_mb_s = (current / 1024 / 1024) / elapsed
            current_mb = current / 1024 / 1024
            total_mb = (total / 1024 / 1024) if total else 0
            percent = (current / total * 100) if total else 0

            print(
                f"[DOWNLOAD] {label}: "
                f"{percent:6.2f}% | "
                f"{current_mb:8.2f}/{total_mb:8.2f} MB | "
                f"{speed_mb_s:6.2f} MB/s",
                end="\r",
                flush=True,
            )

            if total and current >= total:
                print()

        return callback

    async def download_from_message(
        self,
        message,
        romaji_title: str,
        episode_code: Optional[str] = None,
    ) -> str | None:
        if not getattr(message, "media", None):
            return None

        target_path = self.build_target_path(
            romaji_title=romaji_title,
            episode_code=episode_code,
        )

        label = target_path.name
        print(f"[DOWNLOAD] starting: {label}")

        downloaded_path = await message.download_media(
            file=str(target_path),
            progress_callback=self._make_progress_callback(label),
        )
        if not downloaded_path:
            print(f"[DOWNLOAD] failed: {label}")
            return None

        print(f"[DOWNLOAD] completed: {downloaded_path}")
        return str(downloaded_path)

    async def download_from_link(
        self,
        client,
        link: str,
        romaji_title: str,
        episode_code: Optional[str] = None,
    ) -> str | None:
        target_message = await self.get_latest_media_message_in_topic(client, link)
        if not target_message:
            print(f"[DOWNLOAD] no media message found for link: {link}")
            return None

        print(f"[DOWNLOAD] resolved target message id={getattr(target_message, 'id', None)}")

        return await self.download_from_message(
            message=target_message,
            romaji_title=romaji_title,
            episode_code=episode_code,
        )