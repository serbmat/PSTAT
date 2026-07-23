import math

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


PAGE_SIZE = 8


def get_sorted_shows(db) -> list[dict]:
    return sorted(db.get_shows(), key=lambda show: show.get("title", "").lower())


def get_page_slice(items: list[dict], page: int, page_size: int = PAGE_SIZE):
    total_items = len(items)
    total_pages = max(1, math.ceil(total_items / page_size))
    page = max(0, min(page, total_pages - 1))

    start = page * page_size
    end = start + page_size
    return items[start:end], page, total_pages


def build_manage_list_keyboard(
    shows: list[dict],
    page: int,
    page_size: int = PAGE_SIZE
) -> InlineKeyboardMarkup:
    page_items, page, total_pages = get_page_slice(shows, page, page_size)
    start = page * page_size

    builder = InlineKeyboardBuilder()

    for offset, show in enumerate(page_items):
        global_index = start + offset
        builder.row(
            InlineKeyboardButton(
                text=show["title"],
                callback_data=f"ml:show:{global_index}:{page}"
            )
        )

    nav_buttons = []

    if page > 0:
        nav_buttons.append(
            InlineKeyboardButton(text="⬅️ Prev", callback_data=f"ml:page:{page - 1}")
        )

    nav_buttons.append(
        InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="ml:noop")
    )

    if page < total_pages - 1:
        nav_buttons.append(
            InlineKeyboardButton(text="Next ➡️", callback_data=f"ml:page:{page + 1}")
        )

    builder.row(*nav_buttons)
    builder.row(
        InlineKeyboardButton(text="➕ Add Show", callback_data=f"ml:add:{page}")
    )
    builder.row(InlineKeyboardButton(text="❌ Close", callback_data="ml:close"))

    return builder.as_markup()


def build_manage_show_keyboard(global_index: int, page: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🗑 Delete",
                    callback_data=f"ml:delask:{global_index}:{page}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Back",
                    callback_data=f"ml:page:{page}"
                ),
                InlineKeyboardButton(
                    text="❌ Close",
                    callback_data="ml:close"
                ),
            ],
        ]
    )


def build_delete_confirm_keyboard(global_index: int, page: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Confirm Delete",
                    callback_data=f"ml:del:{global_index}:{page}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Back",
                    callback_data=f"ml:show:{global_index}:{page}"
                ),
                InlineKeyboardButton(
                    text="❌ Close",
                    callback_data="ml:close"
                ),
            ],
        ]
    )


def build_normalized_title_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Use title and normalize",
                    callback_data="ml:add:norm:auto"
                )
            ]
        ]
    )


def build_preference_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="dub", callback_data="ml:add:pref:dub"),
                InlineKeyboardButton(text="sub", callback_data="ml:add:pref:sub"),
                InlineKeyboardButton(text="mvo", callback_data="ml:add:pref:mvo"),
            ],
            [
                InlineKeyboardButton(text="Type manually", callback_data="ml:add:pref:custom"),
            ]
        ]
    )



def build_forward_add_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Add", callback_data="ml:fwd:add"),
                InlineKeyboardButton(text="✏️ Edit", callback_data="ml:fwd:edit"),
            ],
            [
                InlineKeyboardButton(text="❌ Cancel", callback_data="ml:fwd:cancel"),
            ],
        ]
    )