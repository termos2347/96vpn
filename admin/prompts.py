import logging
from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from db.crud import add_prompt, get_prompts_by_category, update_prompt, delete_prompt, get_all_categories
from web.services.auth import PromptService
from config import ADMIN_CHAT_ID

logger = logging.getLogger(__name__)
router = Router()

class PromptForm(StatesGroup):
    category = State()
    title = State()
    description = State()
    content = State()
    is_free = State()

@router.message(Command("addprompt"))
async def cmd_addprompt(message: types.Message, state: FSMContext):
    if str(message.from_user.id) != ADMIN_CHAT_ID:
        await message.answer("❌ Нет доступа.")
        return
    await state.set_state(PromptForm.category)
    await message.answer("Введите название категории:")

@router.message(PromptForm.category)
async def process_category(message: types.Message, state: FSMContext):
    cat_name = message.text.strip()
    cats = await get_all_categories()
    if cat_name not in cats:
        await message.answer("Такой категории нет. Сначала создайте её через /addcategory.")
        await state.clear()
        return
    await state.update_data(category=cat_name)
    await state.set_state(PromptForm.title)
    await message.answer("Введите название промпта:")

@router.message(PromptForm.title)
async def process_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await state.set_state(PromptForm.description)
    await message.answer("Введите краткое описание:")

@router.message(PromptForm.description)
async def process_description(message: types.Message, state: FSMContext):
    await state.update_data(description=message.text.strip())
    await state.set_state(PromptForm.content)
    await message.answer("Введите полный текст промпта:")

@router.message(PromptForm.content)
async def process_content(message: types.Message, state: FSMContext):
    await state.update_data(content=message.text.strip())
    await state.set_state(PromptForm.is_free)
    await message.answer("Промпт бесплатный? (да/нет)")

@router.message(PromptForm.is_free)
async def process_is_free(message: types.Message, state: FSMContext):
    answer = message.text.lower().strip()
    is_free = answer in ("да", "yes", "1", "true")
    data = await state.get_data()
    prompt = await add_prompt(
        title=data["title"],
        description=data["description"],
        content=data["content"],
        category_name=data["category"],
        is_free=is_free
    )
    if prompt:
        PromptService.invalidate()
        await message.answer(f"✅ Промпт '{prompt.title}' (ID {prompt.id}) добавлен!")
    else:
        await message.answer("❌ Ошибка при добавлении. Проверьте категорию.")
    await state.clear()

@router.message(Command("editprompt"))
async def cmd_editprompt(message: types.Message):
    if str(message.from_user.id) != ADMIN_CHAT_ID:
        await message.answer("❌ Нет доступа.")
        return
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Используйте: /editprompt <id> <поле=значение> ...")
        return
    try:
        prompt_id = int(args[1])
    except ValueError:
        await message.answer("ID должен быть числом.")
        return
    updates = {}
    for arg in args[2:]:
        if "=" in arg:
            key, val = arg.split("=", 1)
            updates[key] = val
    if not updates:
        await message.answer("Укажите поля для обновления, например: /editprompt 5 title=Новый заголовок is_free=true")
        return
    if await update_prompt(prompt_id, **updates):
        PromptService.invalidate()
        await message.answer("✅ Промпт обновлён.")
    else:
        await message.answer("❌ Промпт не найден или ошибка.")

@router.message(Command("deleteprompt"))
async def cmd_deleteprompt(message: types.Message):
    if str(message.from_user.id) != ADMIN_CHAT_ID:
        await message.answer("❌ Нет доступа.")
        return
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Используйте: /deleteprompt <id>")
        return
    try:
        prompt_id = int(args[1])
    except ValueError:
        await message.answer("ID должен быть числом.")
        return
    if await delete_prompt(prompt_id):
        PromptService.invalidate()
        await message.answer("✅ Промпт удалён.")
    else:
        await message.answer("❌ Промпт не найден.")

@router.message(Command("listprompts"))
async def cmd_listprompts(message: types.Message):
    if str(message.from_user.id) != ADMIN_CHAT_ID:
        await message.answer("❌ Нет доступа.")
        return
    args = message.text.split(maxsplit=1)
    category = args[1] if len(args) > 1 else None
    prompts = await get_prompts_by_category(category)
    if not prompts:
        await message.answer("Промптов не найдено.")
        return
    lines = []
    for p in prompts[:20]:
        lines.append(f"{p['id']}: {p['title']} [{p['category']}] {'(бесплатный)' if p['is_free'] else ''}")
    await message.answer("📋 Промпты:\n" + "\n".join(lines))
    if len(prompts) > 20:
        await message.answer("Показаны первые 20. Уточните категорию.")