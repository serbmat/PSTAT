from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


MAIN_MENU_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="📅 Schedule"),
            KeyboardButton(text="📍 Today"),
            KeyboardButton(text="⏭ Tomorrow"),
        ],
        [
            KeyboardButton(text="🆕 Discovered"),
            KeyboardButton(text="🛠 Manage List"),
        ],
    ],
    resize_keyboard=True,
    is_persistent=True,
    input_field_placeholder="Choose a command..."
)