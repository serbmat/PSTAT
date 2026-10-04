import asyncio
import json
import os
from pathlib import Path

from aiohttp import web
from dotenv import load_dotenv

from core.event_reporter import build_event
from dashboard.store import EventStore

load_dotenv()

VALID_LEVELS = frozenset({"debug", "info", "warning", "error"})
STATIC_DIR = Path(__file__).resolve().parent / "static"


def _check_token(request: web.Request) -> bool:
    expected = request.app.get("dashboard_token")
    if not expected:
        return True
    header = request.headers.get("Authorization", "")
    if header == f"Bearer {expected}":
        return True
    query_token = request.query.get("token")
    return query_token == expected


async def health(_request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def ingest_event(request: web.Request) -> web.Response:
    if not _check_token(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "invalid json"}, status=400)
    if not isinstance(payload, dict):
        return web.json_response({"error": "event must be an object"}, status=400)

    message = payload.get("message")
    category = payload.get("category")
    event_name = payload.get("event")
    if not message or not category or not event_name:
        return web.json_response(
            {"error": "message, category, and event are required"},
            status=400,
        )

    level = str(payload.get("level") or "info").lower()
    if level not in VALID_LEVELS:
        level = "info"

    event = build_event(
        category=str(category),
        event=str(event_name),
        message=str(message),
        level=level,
        source=str(payload.get("source") or ""),
        data=payload.get("data") if isinstance(payload.get("data"), dict) else {},
    )
    if payload.get("id"):
        event["id"] = str(payload["id"])
    if payload.get("ts"):
        event["ts"] = str(payload["ts"])

    store: EventStore = request.app["store"]
    store.add(event)
    return web.json_response({"status": "ok", "id": event["id"]})


async def list_events(request: web.Request) -> web.Response:
    store: EventStore = request.app["store"]
    try:
        limit = int(request.query.get("limit", "200"))
    except ValueError:
        limit = 200
    events = store.query(
        category=request.query.get("category") or None,
        level=request.query.get("level") or None,
        event=request.query.get("event") or None,
        limit=min(limit, 2000),
    )
    events = list(reversed(events))
    return web.json_response({"events": events})


async def stream_events(request: web.Request) -> web.StreamResponse:
    store: EventStore = request.app["store"]
    response = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
    await response.prepare(request)
    queue = store.subscribe()
    try:
        await response.write(b": connected\n\n")
        while True:
            event = await queue.get()
            payload = json.dumps(event, ensure_ascii=False)
            await response.write(f"data: {payload}\n\n".encode("utf-8"))
    except (asyncio.CancelledError, ConnectionResetError, BrokenPipeError):
        pass
    finally:
        store.unsubscribe(queue)
    return response


async def index(_request: web.Request) -> web.FileResponse:
    return web.FileResponse(STATIC_DIR / "index.html")


def create_app() -> web.Application:
    events_path = Path(os.getenv("DASHBOARD_EVENTS_PATH", "data/dashboard_events.jsonl"))
    token = os.getenv("DASHBOARD_TOKEN", "").strip() or None
    app = web.Application()
    app["store"] = EventStore(events_path)
    app["dashboard_token"] = token
    app.router.add_get("/api/health", health)
    app.router.add_post("/api/events", ingest_event)
    app.router.add_get("/api/events", list_events)
    app.router.add_get("/api/stream", stream_events)
    app.router.add_get("/", index)
    if STATIC_DIR.exists():
        app.router.add_static("/static", STATIC_DIR)
    return app


def main() -> None:
    host = os.getenv("DASHBOARD_HOST", "0.0.0.0")
    port = int(os.getenv("DASHBOARD_PORT", "8090"))
    app = create_app()
    web.run_app(app, host=host, port=port)


if __name__ == "__main__":
    main()
