from aiogram.fsm.state import State, StatesGroup


class PaymentStates(StatesGroup):
    waiting_phone = State()
    waiting_screenshot = State()


class CampaignStates(StatesGroup):
    message_text = State()
    select_groups = State()
    enter_group_chat_id = State()
    interval = State()


class LoginStates(StatesGroup):
    phone = State()
    code = State()


class AdminStates(StatesGroup):
    waiting_video = State()
