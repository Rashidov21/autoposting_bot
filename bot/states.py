from aiogram.fsm.state import State, StatesGroup


class CampaignStates(StatesGroup):
    message_text = State()
    select_groups = State()
    enter_group_chat_id = State()
    chat_ids = State()
    interval = State()
    editing_text = State()
    editing_interval = State()


class LoginStates(StatesGroup):
    phone = State()
    code = State()


class AdminStates(StatesGroup):
    waiting_video = State()


class PaymentStates(StatesGroup):
    waiting_phone = State()
    waiting_screenshot = State()
