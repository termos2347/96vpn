import logging
from aiogram import Router, types
from aiogram.filters import Command
from db.crud import add_category, get_all_categories, rename_category, delete_category
from web.services.auth import PromptService
from config import ADMIN_CHAT_ID

logger = logging.getLogger(__name__)
router = Router()

@router.message(Command("addcategory"))
async def cmd_addcategory(message: types.Message):
    if str(message.from_user.id) != ADMIN_CHAT_ID:
        await message.answer("❌ Нет доступа.")
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Используйте: /addcategory <название>")
        return
    name = args[1].strip()
    cat = await add_category(name)
    if cat:
        PromptService.invalidate()
        await message.answer(f"✅ Категория '{name}' создана.")
    else:
        await message.answer(f"❌ Категория '{name}' уже существует.")

@router.message(Command("renamecategory"))
async def cmd_renamecategory(message: types.Message):
    if str(message.from_user.id) != ADMIN_CHAT_ID:
        await message.answer("❌ Нет доступа.")
        return
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.answer("Используйте: /renamecategory <старое> <новое>")
        return
    old, new = args[1], args[2]
    if await rename_category(old, new):
        PromptService.invalidate()
        await message.answer(f"✅ Категория переименована в '{new}'.")
    else:
        await message.answer("❌ Категория не найдена.")

@router.message(Command("deletecategory"))
async def cmd_deletecategory(message: types.Message):
    if str(message.from_user.id) != ADMIN_CHAT_ID:
        await message.answer("❌ Нет доступа.")
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Используйте: /deletecategory <название>")
        return
    name = args[1].strip()
    if await delete_category(name):
        PromptService.invalidate()
        await message.answer(f"✅ Категория '{name}' и все её промпты удалены.")
    else:
        await message.answer("❌ Категория не найдена.")