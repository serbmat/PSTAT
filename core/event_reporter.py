import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

import aiohttp

LOGGER = logging.getLogger(__name__)

VALID_LEVELS = frozenset({"debug", "info", "warning", "error"})
QUEUE_MAXSIZE = 500
POST_TIMEOUT_SECONDS = 1.0

LOGGER_CATEGORIES = {
    "services.telegram.release_monitor": "release_monitor",
    "services.telegram.downloader": "download",
    "services.telegram.user_client": "telegram_client",
    "services.dub_detector": "dub_detector",
    "handlers.webhook": "sonarr",
    "handlers.commands": "bot",
    "handlers.callbacks": "bot",
    "handlers.forwarded_messages": "bot",
    "__main__": "system",
    "main": "system",
}

_reporter: "EventReporter | None" = None


def category_for_logger(name: str) -> str:
    if name in LOGGER_CATEGORIES:
        return LOGGER_CATEGORIES[name]
    for prefix, category in LOGGER_CATEGORIES.items():
        if name.startswith(prefix + ".") or name == prefix:
            return category
    return "system"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_event(
    *,
    category: str,
    event: str,
    message: str,
    level: str = "info",
    source: str = "",
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_level = (level or "info").lower()
    if normalized_level not in VALID_LEVELS:
        normalized_level = "info"
    return {
        "id": str(uuid.uuid4()),
        "ts": _utcnow_iso(),
        "level": normalized_level,
        "category": category or "system",
        "event": event or "log",
        "message": message,
        "source": source or "",
        "data": data or {},
    }


class EventReporter:
    def __init__(
        self,
        dashboard_url: str,
        token: str | None = None,
        enabled: bool = True,
    ):
        self.dashboard_url = dashboard_url.rstrip("/")
        self.token = token or None
        self.enabled = enabled
        self._queue: asyncio.Queue[dict[str, Any]] | None = None
        self._session: aiohttp.ClientSession | None = None
        self._worker_task: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._drop_logged = False

    async def start(self) -> None:
        if not self.enabled:
            LOGGER.info("Dashboard event reporter disabled")
            return
        if not self.dashboard_url:
            LOGGER.warning("DASHBOARD_URL is empty; event reporter disabled")
            self.enabled = False
            return

        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue(maxsize=QUEUE_MAXSIZE)
        self._session = aiohttp.ClientSession()
        self._worker_task = asyncio.create_task(self._worker(), name="dashboard-event-worker")
        LOGGER.info("Dashboard event reporter started, url=%s", self.dashboard_url)

    async def stop(self) -> None:
        if self._queue is not None:
            try:
                await asyncio.wait_for(self._queue.join(), timeout=1.5)
            except (asyncio.TimeoutError, ValueError):
                pass
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None
        if self._session:
            await self._session.close()
            self._session = None
        self._queue = None
        self._loop = None

    def emit(
        self,
        *,
        category: str,
        event: str,
        message: str,
        level: str = "info",
        source: str = "",
        data: dict[str, Any] | None = None,
    ) -> None:
        if not self.enabled:
            return
        payload = build_event(
            category=category,
            event=event,
            message=message,
            level=level,
            source=source,
            data=data,
        )
        self.enqueue(payload)

    def enqueue(self, payload: dict[str, Any]) -> None:
        if not self.enabled or self._queue is None:
            return

        def _put() -> None:
            if self._queue is None:
                return
            try:
                self._queue.put_nowait(payload)
                self._drop_logged = False
            except asyncio.QueueFull:
                if not self._drop_logged:
                    self._drop_logged = True
                    LOGGER.warning("Dashboard event queue full; dropping events")

        loop = self._loop
        if loop is None:
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None

        if running is loop:
            _put()
        else:
            try:
                loop.call_soon_threadsafe(_put)
            except RuntimeError:
                pass

    async def _worker(self) -> None:
        endpoint = f"{self.dashboard_url}/api/events"
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        while True:
            payload = await self._queue.get()  # type: ignore[union-attr]
            try:
                if self._session is None:
                    continue
                timeout = aiohttp.ClientTimeout(total=POST_TIMEOUT_SECONDS)
                async with self._session.post(
                    endpoint,
                    json=payload,
                    headers=headers,
                    timeout=timeout,
                ) as response:
                    if response.status >= 400:
                        LOGGER.debug(
                            "Dashboard POST failed: status=%s",
                            response.status,
                        )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                LOGGER.debug("Dashboard POST failed: %s", exc)
            finally:
                if self._queue is not None:
                    self._queue.task_done()


class HttpLogHandler(logging.Handler):
    def __init__(self, reporter: EventReporter):
        super().__init__()
        self.reporter = reporter

    def emit(self, record: logging.LogRecord) -> None:
        if record.name == LOGGER.name or record.name.startswith("core.event_reporter"):
            return
        if record.name.startswith("aiohttp.access"):
            return
        try:
            message = record.getMessage()
            if not message:
                return
            level_name = record.levelname.lower()
            if level_name == "critical":
                level_name = "error"
            elif level_name not in VALID_LEVELS:
                level_name = "info"
            payload = build_event(
                category=category_for_logger(record.name),
                event="log",
                message=message,
                level=level_name,
                source=record.name,
            )
            self.reporter.enqueue(payload)
        except Exception:
            self.handleError(record)


def emit(
    *,
    category: str,
    event: str,
    message: str,
    level: str = "info",
    source: str = "",
    data: dict[str, Any] | None = None,
) -> None:
    if _reporter is None:
        return
    _reporter.emit(
        category=category,
        event=event,
        message=message,
        level=level,
        source=source,
        data=data,
    )


def install_logging_handler(reporter: EventReporter) -> None:
    root = logging.getLogger()
    for handler in root.handlers:
        if isinstance(handler, HttpLogHandler):
            return
    handler = HttpLogHandler(reporter)
    handler.setLevel(logging.INFO)
    root.addHandler(handler)


async def start_reporter_from_env() -> EventReporter | None:
    global _reporter
    enabled = os.getenv("DASHBOARD_ENABLED", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    dashboard_url = os.getenv("DASHBOARD_URL", "http://127.0.0.1:8090").strip()
    token = os.getenv("DASHBOARD_TOKEN", "").strip() or None
    reporter = EventReporter(
        dashboard_url=dashboard_url,
        token=token,
        enabled=enabled,
    )
    await reporter.start()
    if reporter.enabled:
        install_logging_handler(reporter)
    _reporter = reporter
    return reporter


async def stop_reporter() -> None:
    global _reporter
    if _reporter is None:
        return
    await _reporter.stop()
    _reporter = None
