import json
from datetime import datetime, timezone

from aiohttp import web

from services.sonarr_api import sonarr


def normalize_title(title: str) -> str:
    import re
    return re.sub(r'[^a-z0-9]', '', title.lower())


def get_download_time(payload: dict) -> str:
    episode_file = payload.get("episodeFile", {})
    return episode_file.get("dateAdded") or datetime.now(timezone.utc).astimezone().isoformat()


def build_new_show_record(
    series_title: str,
    normalized_title: str,
    episode_code: str,
    download_time: str,
) -> dict:
    return {
        "title": series_title,
        "normalized_title": normalized_title,
        "preference": "dub",
        "last_downloaded_episode": episode_code,
        "last_download_time": download_time,
    }


def add_show_if_missing(
    db,
    series_title: str,
    normalized_title: str,
    episode_code: str,
    download_time: str,
) -> bool:
    show_record = build_new_show_record(
        series_title=series_title,
        normalized_title=normalized_title,
        episode_code=episode_code,
        download_time=download_time,
    )

    if hasattr(db, "add_show"):
        try:
            result = db.add_show(show_record)
            return True if result is None else bool(result)
        except TypeError:
            try:
                result = db.add_show(
                    title=series_title,
                    normalized_title=normalized_title,
                    preference="unknown",
                    last_downloaded_episode=episode_code,
                    last_download_time=download_time,
                )
                return True if result is None else bool(result)
            except TypeError:
                pass

    if hasattr(db, "load") and hasattr(db, "save"):
        data = db.load()
        shows = data.setdefault("shows", [])

        exists = any(
            show.get("normalized_title") == normalized_title
            for show in shows
        )
        if exists:
            return False

        shows.append(show_record)
        db.save(data)
        return True

    raise RuntimeError(
        "DB object does not support add_show(...) or load()/save()."
    )


async def sonarr_webhook_handler(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
        event_type = payload.get("eventType")

        print(f"[SONARR WEBHOOK] eventType={event_type}")
        # print(json.dumps(payload, ensure_ascii=False, indent=2))

        if event_type != "Download":
            return web.json_response({
                "status": "ignored",
                "reason": f"eventType '{event_type}' is not handled"
            })

        bot = request.app["bot"]
        db = request.app["db"]

        series = payload.get("series", {})
        episodes = payload.get("episodes", [])

        if not series or not episodes:
            return web.json_response({
                "status": "ignored",
                "reason": "missing series or episodes in payload"
            })

        series_title = series.get("title")
        if not series_title:
            return web.json_response({
                "status": "ignored",
                "reason": "series title is missing"
            })

        normalized_title = normalize_title(series_title)

        first_episode = episodes[0]
        season_number = first_episode.get("seasonNumber")
        episode_number = first_episode.get("episodeNumber")
        episode_id = first_episode.get("id")

        if season_number is None or episode_number is None:
            return web.json_response({
                "status": "ignored",
                "reason": "episode season/number missing"
            })

        episode_code = f"S{int(season_number):02d}E{int(episode_number):02d}"
        download_time = get_download_time(payload)

        created = False

        updated = db.update_last_download(
            normalized_title=normalized_title,
            episode=episode_code,
            download_time=download_time
        )

        if not updated:
            created = add_show_if_missing(
                db=db,
                series_title=series_title,
                normalized_title=normalized_title,
                episode_code=episode_code,
                download_time=download_time,
            )

            updated = db.update_last_download(
                normalized_title=normalized_title,
                episode=episode_code,
                download_time=download_time
            )

        print(
            f"[SONARR WEBHOOK] updated={updated} created={created} "
            f"title={series_title} normalized={normalized_title} episode={episode_code}"
        )

        if episode_id:
            try:
                await sonarr.unmonitor_episode(episode_id)
                print(f"[SONARR WEBHOOK] Successfully unmonitored episode {episode_id} in Sonarr.")
            except Exception as e:
                print(f"[SONARR WEBHOOK] Failed to unmonitor episode {episode_id}: {e}")

        return web.json_response({
            "status": "success",
            "updated": updated,
            "created": created,
            "title": series_title,
            "normalized_title": normalized_title,
            "episode_code": episode_code,
            "download_time": download_time,
            "unmonitored": True
        })

    except Exception as e:
        print(f"[SONARR WEBHOOK] error: {e}")
        return web.json_response({
            "status": "error",
            "message": str(e)
        }, status=500)