import asyncio
import json
from collections import deque
from pathlib import Path
from typing import Any

MAX_EVENTS = 2000


class EventStore:
    def __init__(self, jsonl_path: Path, max_events: int = MAX_EVENTS):
        self.jsonl_path = Path(jsonl_path)
        self.max_events = max_events
        self._events: deque[dict[str, Any]] = deque(maxlen=max_events)
        self._subscribers: set[asyncio.Queue] = set()
        self._load()

    def _load(self) -> None:
        if not self.jsonl_path.exists():
            return
        loaded: list[dict[str, Any]] = []
        try:
            with self.jsonl_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        loaded.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except OSError:
            return
        for event in loaded[-self.max_events :]:
            self._events.append(event)

    def add(self, event: dict[str, Any]) -> dict[str, Any]:
        self._events.append(event)
        try:
            self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
            with self.jsonl_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        except OSError:
            pass
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                    queue.put_nowait(event)
                except Exception:
                    pass
        return event

    def query(
        self,
        *,
        category: str | None = None,
        level: str | None = None,
        event: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        items = list(self._events)
        if category:
            items = [item for item in items if item.get("category") == category]
        if level:
            items = [item for item in items if item.get("level") == level]
        if event:
            items = [item for item in items if item.get("event") == event]
        if limit < 1:
            limit = 1
        return items[-limit:]

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)
