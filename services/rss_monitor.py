import asyncio
from datetime import datetime
from email.utils import parsedate_to_datetime

import feedparser

from core.json_db import JsonDB
from utils.text_parser import parse_release


class RSSMonitor:
    def __init__(self, db: JsonDB, feed_url: str, poll_interval: int = 300):
        self.db = db
        self.feed_url = feed_url
        self.poll_interval = poll_interval
        self._seen_links = set()

    def _parse_entry_time(self, entry) -> str | None:
        published = entry.get("published")
        if published:
            try:
                return parsedate_to_datetime(published).isoformat()
            except Exception:
                return None
        return None

    def _matches_show_preference(self, show: dict, parsed_release: dict) -> bool:
        preference = show.get("preference")

        if preference == "dub":
            return parsed_release["is_dub"]

        if preference == "sub":
            return parsed_release["is_multi_sub"]

        return False

    def _is_newer_episode(self, show: dict, parsed_release: dict) -> bool:
        last_episode = show.get("last_downloaded_episode")
        current_episode = parsed_release.get("episode_code")

        if not last_episode:
            return True

        return current_episode != last_episode

    def check_once(self) -> list[dict]:
        feed = feedparser.parse(self.feed_url)
        notifications = []

        for entry in feed.entries:
            link = entry.get("link")
            title = entry.get("title")

            if not title or not link:
                continue

            if link in self._seen_links:
                continue

            parsed_release = parse_release(title)
            if not parsed_release:
                continue

            show = self.db.find_show_by_normalized_title(parsed_release["normalized_title"])

            if show:
                if self._matches_show_preference(show, parsed_release) and self._is_newer_episode(show, parsed_release):
                    notifications.append({
                        "type": "tracked_show",
                        "show": show["title"],
                        "episode_code": parsed_release["episode_code"],
                        "release_title": title,
                        "link": link,
                        "published_at": self._parse_entry_time(entry),
                    })

            else:
                is_episode_1 = parsed_release["episode_code"].endswith("E01")
                if is_episode_1 and parsed_release["is_dub"]:
                    normalized_title = parsed_release["normalized_title"]

                    if not self.db.has_discovered_show(normalized_title):
                        notifications.append({
                            "type": "new_show_discovery",
                            "show": parsed_release["title"],
                            "episode_code": parsed_release["episode_code"],
                            "release_title": title,
                            "link": link,
                            "published_at": self._parse_entry_time(entry),
                        })
                        self.db.add_discovered_show(normalized_title)

            self._seen_links.add(link)

        return notifications

    async def run_forever(self, on_notification):
        while True:
            try:
                notifications = self.check_once()
                for item in notifications:
                    await on_notification(item)
            except Exception as e:
                print(f"[RSSMonitor] Error: {e}")

            await asyncio.sleep(self.poll_interval)