import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import feedparser

from core.json_db import JsonDB
from utils.text_parser import (
    classify_release,
    normalize_title,
)

LOGGER = logging.getLogger(__name__)

NYAA_RSS_URL = "https://nyaa.si/?page=rss&c=1_2&q=(Toonshub%7CVARYG%7CYameii)+(dual%7Cdub)"
STATE_PATH = Path("data/dub_detector_state.json")


@dataclass
class ReleaseEntry:
    entry_id: str
    title: str
    link: str
    published: str
    torrent_url: Optional[str] = None

    @classmethod
    def from_feed_entry(cls, entry) -> "ReleaseEntry":
        torrent_url = None
        for link in getattr(entry, "links", []) or []:
            href = (
                getattr(link, "href", None)
                if not isinstance(link, dict)
                else link.get("href")
            )
            type_ = (
                getattr(link, "type", None)
                if not isinstance(link, dict)
                else link.get("type")
            )
            rel = (
                getattr(link, "rel", None)
                if not isinstance(link, dict)
                else link.get("rel")
            )
            if href and (
                href.endswith(".torrent")
                or rel == "enclosure"
                or type_ == "application/x-bittorrent"
            ):
                torrent_url = href
                break

        entry_id = (
            getattr(entry, "id", None)
            or getattr(entry, "guid", None)
            or getattr(entry, "link", None)
            or getattr(entry, "title", "")
        )
        return cls(
            entry_id=str(entry_id),
            title=getattr(entry, "title", "").strip(),
            link=getattr(entry, "link", "").strip(),
            published=getattr(entry, "published", "").strip(),
            torrent_url=torrent_url,
        )


class DubDetector:
    def __init__(
        self,
        bot,
        notify_chat_id: str,
        db: JsonDB,
        rss_url: str = NYAA_RSS_URL,
        state_path: Path = STATE_PATH,
    ):
        self.bot = bot
        self.notify_chat_id = notify_chat_id
        self.db = db
        self.rss_url = rss_url
        self.state_path = Path(state_path)

    def _extract_show_info_from_rss_title(self, raw_title: str) -> Optional[Dict[str, str]]:
        """
        Extract show title and normalized title from an RSS entry title.
        RSS titles are usually like:
          [ToonsHub] The Angel Next Door Spoils Me Rotten S01 1080p ...
        """
        import re

        title = raw_title.strip()
        if title.startswith("["):
            bracket_end = title.find("]")
            if bracket_end != -1:
                title = title[bracket_end + 1 :].strip()

        season_match = re.search(r"\sS\d{2}(?:E\d{2})?", title, re.IGNORECASE)
        if season_match:
            title = title[: season_match.start()].strip()

        if not title:
            return None

        normalized = normalize_title(title)
        return {
            "title": title,
            "normalized_title": normalized,
        }

    def _is_show_already_tracked(self, normalized_title: str) -> bool:
        # Check in shows
        for s in self.db.get_shows():
            if s.get("normalized_title") == normalized_title:
                return True

        # Check in discovered_shows (now dicts, not strings)
        for s in self.db.get_discovered_shows():
            # Support both old string format and new dict format
            if isinstance(s, str):
                if s == normalized_title:
                    return True
            elif isinstance(s, dict):
                if s.get("normalized_title") == normalized_title:
                    return True

        return False

    def _add_discovered_show(self, title: str, normalized_title: str, release_kind: str) -> None:
        # Avoid duplicates
        if self._is_show_already_tracked(normalized_title):
            return

        discovered = self.db.get_discovered_shows()

        # If your DB still uses the old list[str] format, you can either:
        # 1) migrate to list[dict] in core.json_db, or
        # 2) store dicts here and adjust get_discovered_shows() to always return list[dict].
        #
        # Assuming you updated get_discovered_shows() to return list[dict], do:
        data = self.db.load()
        disc_list = data.setdefault("discovered_shows", [])

        for s in disc_list:
            if isinstance(s, dict) and s.get("normalized_title") == normalized_title:
                return
            if isinstance(s, str) and s == normalized_title:
                # Optionally migrate old string entry to dict format here
                return

        disc_list.append(
            {
                "title": title,
                "normalized_title": normalized_title,
                "first_seen": datetime.now(timezone.utc).isoformat(),
                "first_seen_type": release_kind,
            }
        )
        self.db.save(data)

    def fetch_feed(self) -> List[ReleaseEntry]:
        parsed = feedparser.parse(self.rss_url)
        if getattr(parsed, "bozo", 0):
            LOGGER.warning(
                "RSS feed parsed with warnings: %s",
                getattr(parsed, "bozo_exception", None),
            )
        return [ReleaseEntry.from_feed_entry(entry) for entry in getattr(parsed, "entries", [])]

    def load_state(self) -> Optional[Dict[str, str]]:
        if not self.state_path.exists():
            return None
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception as exc:
            LOGGER.warning("Failed to read state file %s: %s", self.state_path, exc)
            return None

    def save_state(self, release: ReleaseEntry) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "last_seen_id": release.entry_id,
            "last_seen_title": release.title,
            "last_seen_published": release.published,
            "last_seen_link": release.link,
        }
        self.state_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def build_notification_text(self, release: ReleaseEntry, release_kind: str, show_title: str) -> str:
        kind_label_map = {
            "first_episode": "New dubbed first episode",
            "season_batch": "New dubbed season batch",
            "movie": "New dubbed movie",
        }
        kind_label = kind_label_map.get(release_kind, "New dubbed release")
        lines = [
            "🎙️ <b>Dub detector</b>",
            "",
            f"<b>{kind_label}</b>",
            f"{show_title}",
            f"<i>({release.title})</i>",
        ]
        if release.link:
            lines.append(f'<a href="{release.link}">Open release</a>')
        return "\n".join(lines)

    async def notify(self, release: ReleaseEntry, release_kind: str, show_title: str) -> None:
        if not self.bot or not self.notify_chat_id:
            LOGGER.info("Matched %s: %s", release_kind, release.title)
            return

        text = self.build_notification_text(release, release_kind, show_title)
        await self.bot.send_message(
            chat_id=self.notify_chat_id,
            text=text,
            disable_web_page_preview=True,
        )

    async def check_once(self) -> List[ReleaseEntry]:
        entries = self.fetch_feed()
        if not entries:
            LOGGER.info("No RSS entries returned from %s", self.rss_url)
            return []

        latest = entries[0]
        state = self.load_state()

        if state is None:
            LOGGER.info("No existing dub detector state found; initializing from latest release.")
            self.save_state(latest)
            return [latest]

        last_seen_id = state.get("last_seen_id")
        unseen: List[ReleaseEntry] = []
        for entry in entries:
            if entry.entry_id == last_seen_id:
                break
            unseen.append(entry)

        if not unseen:
            LOGGER.info("No new releases since last check.")
            return []

        unseen.reverse()
        matched: List[ReleaseEntry] = []

        for entry in unseen:
            release_kind = classify_release(entry.title)
            if not release_kind:
                continue

            show_info = self._extract_show_info_from_rss_title(entry.title)
            if not show_info:
                LOGGER.info("Could not extract show title from: %s", entry.title)
                continue

            title = show_info["title"]
            normalized_title = show_info["normalized_title"]

            if self._is_show_already_tracked(normalized_title):
                LOGGER.info(
                    "Show already tracked (normalized=%s); skipping notification for: %s",
                    normalized_title,
                    entry.title,
                )
                continue

            # New show: record and notify
            self._add_discovered_show(title, normalized_title, release_kind)
            await self.notify(entry, release_kind, title)
            matched.append(entry)

        self.save_state(latest)
        LOGGER.info("Processed %s new releases, matched %s.", len(unseen), len(matched))
        return matched