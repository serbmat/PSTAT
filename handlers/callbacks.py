import os
import re

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from core.json_db import JsonDB
from keyboards.manage_list import (
    PAGE_SIZE,
    build_delete_confirm_keyboard,
    build_forward_add_confirm_keyboard,
    build_manage_list_keyboard,
    build_manage_show_keyboard,
    build_normalized_title_keyboard,
    build_preference_keyboard,
    get_sorted_shows,
)
from states.manage_list import AddShowStates


router = Router()

DATABASE_PATH = os.getenv("DATABASE_PATH", "data/database.json")
DB = JsonDB(DATABASE_PATH)


def normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]", "", title.lower())


def get_show_by_global_index(global_index: int) -> tuple[dict | None, list[dict]]:
    shows = get_sorted_shows(DB)

    if global_index < 0 or global_index >= len(shows):
        return None, shows

    return shows[global_index], shows


def format_show_details(show: dict) -> str:
    preference = show.get("preference", "unknown")
    last_episode = show.get("last_downloaded_episode", "Unknown")
    last_time = show.get("last_download_time", "Unknown")

    return (
        f"<b>{show['title']}</b>\n"
        f"Preference: <b>{preference}</b>\n"
        f"Last downloaded episode: <b>{last_episode}</b>\n"
        f"Last download time: <b>{last_time}</b>"
    )


@router.callback_query(F.data == "ml:noop")
async def handle_manage_noop(callback: CallbackQuery):
    await callback.answer()


@router.callback_query(F.data == "ml:close")
async def handle_manage_close(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Manage list closed.")
    await callback.answer()


@router.callback_query(F.data.startswith("ml:page:"))
async def handle_manage_page(callback: CallbackQuery, state: FSMContext):
    await state.clear()

    try:
        page = int(callback.data.split(":")[2])
    except (ValueError, IndexError):
        await callback.answer("Invalid page.", show_alert=True)
        return

    shows = get_sorted_shows(DB)

    if not shows:
        await callback.message.edit_text(
            "<b>Tracked list is empty.</b>",
            reply_markup=build_manage_list_keyboard([], page=0)
        )
        await callback.answer()
        return

    await callback.message.edit_text(
        "<b>Manage tracked shows</b>\nChoose a show to edit.",
        reply_markup=build_manage_list_keyboard(shows, page=page)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ml:show:"))
async def handle_manage_show(callback: CallbackQuery):
    try:
        _, _, global_index, page = callback.data.split(":")
        global_index = int(global_index)
        page = int(page)
    except (ValueError, IndexError):
        await callback.answer("Invalid selection.", show_alert=True)
        return

    show, _ = get_show_by_global_index(global_index)

    if not show:
        await callback.answer("Show not found.", show_alert=True)
        return

    await callback.message.edit_text(
        format_show_details(show),
        reply_markup=build_manage_show_keyboard(global_index, page)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ml:delask:"))
async def handle_delete_ask(callback: CallbackQuery):
    try:
        _, _, global_index, page = callback.data.split(":")
        global_index = int(global_index)
        page = int(page)
    except (ValueError, IndexError):
        await callback.answer("Invalid selection.", show_alert=True)
        return

    show, _ = get_show_by_global_index(global_index)

    if not show:
        await callback.answer("Show not found.", show_alert=True)
        return

    await callback.message.edit_text(
        f"Delete <b>{show['title']}</b> from tracked list?",
        reply_markup=build_delete_confirm_keyboard(global_index, page)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ml:del:"))
async def handle_delete_confirm(callback: CallbackQuery):
    try:
        _, _, global_index, page = callback.data.split(":")
        global_index = int(global_index)
        page = int(page)
    except (ValueError, IndexError):
        await callback.answer("Invalid delete request.", show_alert=True)
        return

    show, _ = get_show_by_global_index(global_index)

    if not show:
        await callback.answer("Show not found.", show_alert=True)
        return

    removed = DB.remove_show(show["normalized_title"])

    if not removed:
        await callback.answer("Could not delete show.", show_alert=True)
        return

    shows_after = get_sorted_shows(DB)

    if not shows_after:
        await callback.message.edit_text(
            "<b>Tracked list is empty.</b>",
            reply_markup=build_manage_list_keyboard([], page=0)
        )
        await callback.answer("Deleted.")
        return

    max_page = max(0, (len(shows_after) - 1) // PAGE_SIZE)
    page = min(page, max_page)

    await callback.message.edit_text(
        f"Deleted <b>{show['title']}</b>.\n\nChoose a show to edit.",
        reply_markup=build_manage_list_keyboard(shows_after, page=page)
    )
    await callback.answer("Deleted.")


@router.callback_query(F.data == "ml:add:norm:auto")
async def handle_add_show_normalized_auto(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    title = data.get("title")

    if not title:
        await callback.answer("Title is missing.", show_alert=True)
        return

    normalized_title = normalize_title(title)
    await state.update_data(normalized_title=normalized_title)
    await state.set_state(AddShowStates.waiting_for_preference)

    await callback.message.edit_text(
        f"Normalized title: <b>{normalized_title}</b>\nNow choose preference.",
        reply_markup=build_preference_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ml:add:pref:"))
async def handle_add_show_preference(callback: CallbackQuery, state: FSMContext):
    preference = callback.data.split(":")[-1]

    if preference == "custom":
        await state.set_state(AddShowStates.waiting_for_custom_preference)
        await callback.message.answer("Type custom preference.")
        await callback.answer()
        return

    data = await state.get_data()
    title = data.get("title")
    normalized_title = data.get("normalized_title")
    page = data.get("page", 0)

    if not title or not normalized_title:
        await callback.answer("Missing form data.", show_alert=True)
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
        await callback.message.answer("Show with this normalized title already exists.")
        await callback.answer()
        return

    shows = get_sorted_shows(DB)
    await callback.message.answer(
        f"Added <b>{title}</b> with preference <b>{preference}</b>."
    )
    await callback.message.answer(
        "<b>Manage tracked shows</b>\nChoose a show to edit.",
        reply_markup=build_manage_list_keyboard(shows, page=page)
    )
    await callback.answer("Added.")


@router.callback_query(F.data.regexp(r"^ml:add:\d+$"))
async def handle_add_show_start(callback: CallbackQuery, state: FSMContext):
    try:
        page = int(callback.data.split(":")[2])
    except ValueError:
        page = 0

    await state.clear()
    await state.update_data(page=page)
    await state.set_state(AddShowStates.waiting_for_title)

    await callback.message.answer("Send show title.")
    await callback.answer()


@router.callback_query(F.data == "ml:fwd:cancel")
async def handle_forward_add_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Forwarded add canceled.")
    await callback.answer()


@router.callback_query(F.data == "ml:fwd:add")
async def handle_forward_add_confirm(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()

    title = data.get("title")
    normalized_title = data.get("normalized_title")
    preference = data.get("preference", "mvo")

    if not title or not normalized_title:
        await state.clear()
        await callback.message.edit_text("Missing parsed data. Start again.")
        await callback.answer()
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
        await callback.message.edit_text(
            f"Show <b>{title}</b> already exists in tracked list."
        )
        await callback.answer("Already exists.")
        return

    await callback.message.edit_text(
        f"Added <b>{title}</b> to tracked list.\n"
        f"Preference: <b>{preference}</b>"
    )
    await callback.answer("Added.")


@router.callback_query(F.data == "ml:fwd:edit")
async def handle_forward_add_edit(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    title = data.get("title")

    if not title:
        await state.clear()
        await callback.message.edit_text("Missing parsed data. Start again.")
        await callback.answer()
        return

    await state.set_state(AddShowStates.waiting_for_title)
    await callback.message.edit_text(
        f"Current parsed title: <b>{title}</b>\n\n"
        "Send new show title."
    )
    await callback.answer()