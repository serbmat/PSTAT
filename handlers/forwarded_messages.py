from datetime import timezone

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from keyboards.manage_list import build_forward_add_confirm_keyboard
from states.manage_list import AddShowStates
from utils.text_parser import (
    extract_episode_code,
    extract_normalized_show_title,
    extract_show_romaji_name,
    extract_show_ukrainian_title,
    has_mvo_release_tag,
)


router = Router()


def _format_forward_preview(data: dict) -> str:
    title = data.get("title") or "unknown"
    normalized_title = data.get("normalized_title") or "unknown"
    preference = data.get("preference") or "unknown"
    episode_code = data.get("last_downloaded_episode") or "unknown"
    timestamp = data.get("last_download_time") or "unknown"
    romaji_title = data.get("romaji_title") or "unknown"

    return (
        "<b>Parsed forwarded release</b>\n"
        f"Title: <b>{title}</b>\n"
        f"Romaji: <b>{romaji_title}</b>\n"
        f"Normalized title: <b>{normalized_title}</b>\n"
        f"Preference: <b>{preference}</b>\n"
        f"Episode: <b>{episode_code}</b>\n"
        f"Timestamp: <b>{timestamp}</b>\n\n"
        "Add this show?"
    )


@router.message(F.forward_origin)
async def handle_forwarded_release_message(message: Message, state: FSMContext):
    text = message.text or message.caption or ""
    if not text:
        return

    if not has_mvo_release_tag(text):
        await message.answer("Forwarded message is not an MVO release post.")
        return

    ukrainian_title = extract_show_ukrainian_title(text)
    romaji_title = extract_show_romaji_name(text)
    normalized_title = extract_normalized_show_title(text)

    if not ukrainian_title:
        await message.answer("Could not parse Ukrainian title from forwarded message.")
        return

    if not normalized_title:
        await message.answer("Could not parse normalized title from forwarded message.")
        return

    episode_code = extract_episode_code(text)

    msg_dt = message.forward_date or message.date
    if msg_dt is not None:
        if msg_dt.tzinfo is None:
            msg_dt = msg_dt.replace(tzinfo=timezone.utc)
        timestamp = msg_dt.astimezone().isoformat()
    else:
        timestamp = None

    await state.clear()
    await state.update_data(
        title=ukrainian_title,
        romaji_title=romaji_title,
        normalized_title=normalized_title,
        preference="mvo",
        last_downloaded_episode=episode_code,
        last_download_time=timestamp,
        add_mode="forwarded",
    )
    await state.set_state(AddShowStates.waiting_for_forward_confirm)

    data = await state.get_data()
    await message.answer(
        _format_forward_preview(data),
        reply_markup=build_forward_add_confirm_keyboard(),
    )