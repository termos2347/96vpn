from aiogram.fsm.state import StatesGroup, State

class ServerForm(StatesGroup):
    name = State()
    base_url = State()
    inbound_id = State()
    username = State()
    password = State()
    weight = State()