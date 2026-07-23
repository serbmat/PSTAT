from aiogram.fsm.state import State, StatesGroup


class AddShowStates(StatesGroup):
    waiting_for_title = State()
    waiting_for_normalized_title = State()
    waiting_for_preference = State()
    waiting_for_custom_preference = State()
    waiting_for_forward_confirm = State()