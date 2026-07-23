import json
import threading
from copy import deepcopy
from pathlib import Path


DEFAULT_DATA = {
    "shows": [],
    "discovered_shows": []
}


class JsonDB:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self._lock = threading.Lock()

    def ensure_exists(self) -> None:
        if not self.db_path.exists():
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self.save(DEFAULT_DATA)

    def load(self) -> dict:
        self.ensure_exists()
        with self._lock:
            with self.db_path.open("r", encoding="utf-8") as f:
                data = json.load(f)

        if "shows" not in data:
            data["shows"] = []
        if "discovered_shows" not in data:
            data["discovered_shows"] = []

        return data

    def save(self, data: dict) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        with self._lock:
            with self.db_path.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

    def get_shows(self) -> list[dict]:
        data = self.load()
        return data["shows"]

    def get_discovered_shows(self) -> list[str]:
        data = self.load()
        return data["discovered_shows"]

    def find_show_by_normalized_title(self, normalized_title: str) -> dict | None:
        for show in self.get_shows():
            if show.get("normalized_title") == normalized_title:
                return show
        return None

    def has_discovered_show(self, normalized_title: str) -> bool:
        data = self.load()
        return normalized_title in data["discovered_shows"]

    def add_discovered_show(self, normalized_title: str) -> bool:
        data = self.load()

        if normalized_title in data["discovered_shows"]:
            return False

        data["discovered_shows"].append(normalized_title)
        self.save(data)
        return True

    def add_show(self, show_data: dict) -> bool:
        data = self.load()
        normalized_title = show_data.get("normalized_title")

        if not normalized_title:
            raise ValueError("show_data must contain 'normalized_title'")

        existing = next(
            (show for show in data["shows"] if show.get("normalized_title") == normalized_title),
            None
        )
        if existing:
            return False

        data["shows"].append(show_data)
        self.save(data)
        return True

    def remove_show(self, normalized_title: str) -> bool:
        data = self.load()
        original_len = len(data["shows"])

        data["shows"] = [
            show for show in data["shows"]
            if show.get("normalized_title") != normalized_title
        ]

        if len(data["shows"]) == original_len:
            return False

        self.save(data)
        return True

    def update_show(self, normalized_title: str, **fields) -> bool:
        data = self.load()

        for show in data["shows"]:
            if show.get("normalized_title") == normalized_title:
                show.update(fields)
                self.save(data)
                return True

        return False

    def update_last_download(self, normalized_title: str, episode: str, download_time: str) -> bool:
        return self.update_show(
            normalized_title,
            last_downloaded_episode=episode,
            last_download_time=download_time
        )

    def clear_discovered_shows(self) -> None:
        data = self.load()
        data["discovered_shows"] = []
        self.save(data)

    def get_all_data_copy(self) -> dict:
        return deepcopy(self.load())