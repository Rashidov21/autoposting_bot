from aiogram.fsm.state import State, StatesGroup


class CampaignStates(StatesGroup):
    message_text = State()
    chat_ids = State()
    interval = State()


class LoginStates(StatesGroup):
    phone = State()
    code = State()
