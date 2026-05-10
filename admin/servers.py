import logging
from urllib.parse import urlparse
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from config import ADMIN_CHAT_ID
from db.crud_servers import add_server, get_all_servers, update_server, delete_server
from handlers import get_server_pool
from .server_states import ServerForm

logger = logging.getLogger(__name__)
router = Router()

def is_admin(user_id: int) -> bool:
    return str(user_id) == ADMIN_CHAT_ID

def parse_panel_url(url: str):
    """Извлекает host, port, api_path из полного URL панели 3x‑UI."""
    parsed = urlparse(url)
    host = parsed.hostname
    port = parsed.port if parsed.port else 443
    api_path = parsed.path.rstrip('/')
    return host, port, api_path

# ----- Поэтапное добавление сервера -----
@router.message(Command("addserver"))
async def cmd_addserver_start(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа.")
        return
    await state.set_state(ServerForm.name)
    await message.answer("Введите название сервера (например, Main Server):")

@router.message(ServerForm.name)
async def process_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(ServerForm.base_url)
    await message.answer(
        "Введите полный URL панели 3x‑UI (например, https://185.5.75.235:42347/cNDsqfzYXWpCBcaddZ):"
    )

@router.message(ServerForm.base_url)
async def process_base_url(message: types.Message, state: FSMContext):
    raw_url = message.text.strip()
    try:
        host, port, api_path = parse_panel_url(raw_url)
    except Exception as e:
        await message.answer(f"Не удалось распознать URL: {e}\nПопробуйте ещё раз:")
        return
    await state.update_data(base_url=raw_url, host=host, port=port, api_path=api_path)
    await state.set_state(ServerForm.inbound_id)
    await message.answer("Введите inbound_id (ID входящего подключения в 3x‑UI):")

@router.message(ServerForm.inbound_id)
async def process_inbound_id(message: types.Message, state: FSMContext):
    try:
        inbound_id = int(message.text.strip())
    except ValueError:
        await message.answer("inbound_id должен быть числом. Попробуйте ещё раз:")
        return
    await state.update_data(inbound_id=inbound_id)
    await state.set_state(ServerForm.username)
    await message.answer("Введите имя пользователя для доступа к 3x‑UI:")

@router.message(ServerForm.username)
async def process_username(message: types.Message, state: FSMContext):
    await state.update_data(username=message.text.strip())
    await state.set_state(ServerForm.password)
    await message.answer("Введите пароль для доступа к 3x‑UI:")

@router.message(ServerForm.password)
async def process_password(message: types.Message, state: FSMContext):
    await state.update_data(password=message.text.strip())
    await state.set_state(ServerForm.weight)
    await message.answer("Введите вес сервера (целое число, чем больше, тем чаще будет выбираться). По умолчанию 1:")

@router.message(ServerForm.weight)
async def process_weight(message: types.Message, state: FSMContext):
    weight_str = message.text.strip()
    weight = int(weight_str) if weight_str.isdigit() else 1
    data = await state.get_data()
    server = await add_server(
        name=data['name'],
        host=data['host'],
        port=data['port'],
        inbound_id=data['inbound_id'],
        username=data['username'],
        password=data['password'],
        api_path=data['api_path'],
        sub_port=2096,
        weight=weight
    )
    if server:
        pool = get_server_pool()
        await pool.refresh_servers()
        await message.answer(
            f"✅ Сервер '{data['name']}' добавлен с ID {server.id}\n"
            f"URL: {data['base_url']}\n"
            f"Вес: {weight}"
        )
    else:
        await message.answer(f"❌ Сервер с именем '{data['name']}' уже существует.")
    await state.clear()

# ----- Вспомогательные команды -----
@router.message(Command("listservers"))
async def cmd_listservers(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа.")
        return
    servers = await get_all_servers()
    if not servers:
        await message.answer("Нет добавленных серверов.")
        return
    text = "📋 Список серверов:\n\n"
    for s in servers:
        text += (
            f"ID: {s.id}\n"
            f"Название: {s.name}\n"
            f"URL: https://{s.host}:{s.port}{s.api_path or ''}\n"
            f"Активен: {'✅' if s.is_active else '❌'}\n"
            f"Вес: {s.weight}\n"
            f"-----------------\n"
        )
    await message.answer(text)

@router.message(Command("removeserver"))
async def cmd_removeserver(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа.")
        return
    args = message.text.split()
    if len(args) != 2:
        await message.answer("Используйте: /removeserver <id>")
        return
    try:
        server_id = int(args[1])
    except ValueError:
        await message.answer("ID должен быть числом.")
        return

    # Проверяем, есть ли пользователи с таким server_id
    from sqlalchemy import select, func
    from db.base import AsyncSessionLocal
    from db.models import BotUser

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(func.count()).select_from(BotUser).where(BotUser.server_id == server_id)
        )
        count = result.scalar() or 0
        if count > 0:
            await message.answer(
                f"❌ Невозможно удалить сервер (ID {server_id}), так как к нему привязано {count} пользователей.\n"
                "Сначала отзовите подписки у этих пользователей или переназначьте их на другой сервер."
            )
            return

    # Если нет пользователей – удаляем
    if await delete_server(server_id):
        pool = get_server_pool()
        await pool.refresh_servers()
        await message.answer(f"✅ Сервер {server_id} удалён.")
    else:
        await message.answer("❌ Сервер не найден.")

@router.message(Command("serversetactive"))
async def cmd_serversetactive(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа.")
        return
    args = message.text.split()
    if len(args) != 3:
        await message.answer("Используйте: /serversetactive <id> <0|1>")
        return
    try:
        server_id = int(args[1])
        is_active = bool(int(args[2]))
    except ValueError:
        await message.answer("ID и статус (0 или 1) должны быть числами.")
        return
    if await update_server(server_id, is_active=is_active):
        pool = get_server_pool()
        await pool.refresh_servers()
        await message.answer(f"✅ Статус сервера {server_id} изменён на {'активен' if is_active else 'неактивен'}.")
    else:
        await message.answer("❌ Сервер не найден.")