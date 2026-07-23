import os
import re

from aiogram.fsm.context import FSMContext
from states.manage_list import AddShowStates
from keyboards.manage_list import build_normalized_title_keyboard, build_preference_keyboard

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from core.json_db import JsonDB
from keyboards.main_menu import MAIN_MENU_KEYBOARD
from keyboards.manage_list import build_manage_list_keyboard, get_sorted_shows


router = Router()

DATABASE_PATH = os.getenv("DATABASE_PATH", "data/database.json")
DB = JsonDB(DATABASE_PATH)
LOCAL_TZ = ZoneInfo("Europe/Kyiv")

WEEKDAY_NAMES = {
    0: "Monday",
    1: "Tuesday",
    2: "Wednesday",
    3: "Thursday",
    4: "Friday",
    5: "Saturday",
    6: "Sunday",
}


def normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]", "", title.lower())


def parse_iso_datetime(value: str) -> datetime | None:
    if not value:
        return None

    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=LOCAL_TZ)
        return dt.astimezone(LOCAL_TZ)
    except Exception:
        return None


def estimate_next_release(show: dict) -> datetime | None:
    last_download_time = show.get("last_download_time")
    dt = parse_iso_datetime(last_download_time)

    if not dt:
        return None

    return dt + timedelta(days=7)


def format_show_line(show: dict, next_release: datetime) -> str:
    episode = show.get("last_downloaded_episode", "Unknown")
    preference = show.get("preference", "?")
    time_str = next_release.strftime("%H:%M")
    return f"• {time_str} — <b>{show['title']}</b> ({preference}, after {episode})"


def sort_key_by_time(item: dict):
    return item["next_release"].timetz()


def get_schedule_items() -> list[dict]:
    shows = DB.get_shows()
    items = []

    for show in shows:
        next_release = estimate_next_release(show)
        if not next_release:
            continue

        items.append({
            "show": show,
            "next_release": next_release,
            "weekday": next_release.weekday(),
        })

    items.sort(key=sort_key_by_time)
    return items


async def send_main_menu(message: Message, text: str):
    await message.answer(text, reply_markup=MAIN_MENU_KEYBOARD)


@router.message(Command("start"))
async def cmd_start(message: Message):
    text = (
        "Hello. Use the menu below or commands:\n"
        "/schedule — Weekly tracked schedule\n"
        "/today — Shows for today\n"
        "/tomorrow — Shows for tomorrow\n"
        "/discovered — Discovered dubbed shows\n"
        "/manage — Manage tracked list"
    )
    await send_main_menu(message, text)


@router.message(Command("menu"))
async def cmd_menu(message: Message):
    await send_main_menu(message, "Main menu opened.")


@router.message(Command("schedule"))
@router.message(F.text == "📅 Schedule")
async def cmd_schedule(message: Message):
    items = get_schedule_items()

    if not items:
        await message.answer("Schedule is empty.", reply_markup=MAIN_MENU_KEYBOARD)
        return

    grouped = {i: [] for i in range(7)}
    for item in items:
        grouped[item["weekday"]].append(item)

    lines = ["<b>Estimated weekly schedule</b>"]

    for weekday in range(7):
        day_items = grouped[weekday]
        if not day_items:
            continue

        lines.append("")
        lines.append(f"<b>{WEEKDAY_NAMES[weekday]}</b>")

        day_items.sort(key=sort_key_by_time)
        for item in day_items:
            lines.append(format_show_line(item["show"], item["next_release"]))

    await message.answer("\n".join(lines), reply_markup=MAIN_MENU_KEYBOARD)


@router.message(Command("today"))
@router.message(F.text == "📍 Today")
async def cmd_today(message: Message):
    now = datetime.now(LOCAL_TZ)
    today_weekday = now.weekday()

    items = [item for item in get_schedule_items() if item["weekday"] == today_weekday]
    items.sort(key=sort_key_by_time)

    if not items:
        await message.answer("No shows scheduled for today.", reply_markup=MAIN_MENU_KEYBOARD)
        return

    lines = [f"<b>Today — {WEEKDAY_NAMES[today_weekday]}</b>"]
    for item in items:
        lines.append(format_show_line(item["show"], item["next_release"]))

    await message.answer("\n".join(lines), reply_markup=MAIN_MENU_KEYBOARD)


@router.message(Command("tomorrow"))
@router.message(F.text == "⏭ Tomorrow")
async def cmd_tomorrow(message: Message):
    tomorrow = datetime.now(LOCAL_TZ) + timedelta(days=1)
    tomorrow_weekday = tomorrow.weekday()

    items = [item for item in get_schedule_items() if item["weekday"] == tomorrow_weekday]
    items.sort(key=sort_key_by_time)

    if not items:
        await message.answer("No shows scheduled for tomorrow.", reply_markup=MAIN_MENU_KEYBOARD)
        return

    lines = [f"<b>Tomorrow — {WEEKDAY_NAMES[tomorrow_weekday]}</b>"]
    for item in items:
        lines.append(format_show_line(item["show"], item["next_release"]))

    await message.answer("\n".join(lines), reply_markup=MAIN_MENU_KEYBOARD)


@router.message(Command("discovered"))
@router.message(F.text == "🆕 Discovered")
async def cmd_discovered(message: Message):
    discovered = DB.get_discovered_shows()

    if not discovered:
        await message.answer("No discovered shows yet.", reply_markup=MAIN_MENU_KEYBOARD)
        return

    lines = ["<b>Discovered dubbed shows</b>"]
    for title in discovered:
        lines.append(f"• {title}")

    await message.answer("\n".join(lines), reply_markup=MAIN_MENU_KEYBOARD)


@router.message(Command("manage"))
@router.message(F.text == "🛠 Manage List")
async def cmd_manage_list(message: Message):
    shows = get_sorted_shows(DB)

    if not shows:
        await message.answer("Tracked list is empty.", reply_markup=MAIN_MENU_KEYBOARD)
        return

    await message.answer(
        "<b>Manage tracked shows</b>\nChoose a show to edit.",
        reply_markup=build_manage_list_keyboard(shows, page=0)
    )
    
    






@router.message(AddShowStates.waiting_for_title)
async def process_add_show_title(message: Message, state: FSMContext):
    title = (message.text or "").strip()
    if not title:
        await message.answer("Title cannot be empty. Send show title.")
        return

    await state.update_data(title=title)
    await state.set_state(AddShowStates.waiting_for_normalized_title)

    await message.answer(
        f"Title saved: <b>{title}</b>\n"
        "Send normalized title manually or press the button below.",
        reply_markup=build_normalized_title_keyboard()
    )


@router.message(AddShowStates.waiting_for_normalized_title)
async def process_add_show_normalized_title(message: Message, state: FSMContext):
    normalized_title = normalize_title((message.text or "").strip())
    if not normalized_title:
        await message.answer("Normalized title cannot be empty. Send it again.")
        return

    await state.update_data(normalized_title=normalized_title)
    await state.set_state(AddShowStates.waiting_for_preference)

    await message.answer(
        f"Normalized title saved: <b>{normalized_title}</b>\nChoose preference.",
        reply_markup=build_preference_keyboard()
    )


@router.message(AddShowStates.waiting_for_custom_preference)
async def process_add_show_custom_preference(message: Message, state: FSMContext):
    preference = (message.text or "").strip()
    if not preference:
        await message.answer("Preference cannot be empty. Type custom preference.")
        return

    data = await state.get_data()
    title = data.get("title")
    normalized_title = data.get("normalized_title")
    page = data.get("page", 0)

    if not title or not normalized_title:
        await message.answer("Missing form data. Start again.")
        await state.clear()
        return

    show_data = {
        "title": title,
        "normalized_title": normalized_title,
        "preference": preference,
    }

    if data.get("last_downloaded_episode"):
        show_data["last_downloaded_episode"] = data["last_downloaded_episode"]
    if data.get("last_download_time"):
        show_data["last_download_time"] = data["last_download_time"]

    added = DB.add_show(show_data)

    await state.clear()

    if not added:
        await message.answer("Show with this normalized title already exists.")
        return

    shows = get_sorted_shows(DB)
    await message.answer(f"Added <b>{title}</b> with preference <b>{preference}</b>.")
    await message.answer(
        "<b>Manage tracked shows</b>\nChoose a show to edit.",
        reply_markup=build_manage_list_keyboard(shows, page=page)
    )