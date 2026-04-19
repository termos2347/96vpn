from aiogram import Router, F, types

router = Router()

@router.message(F.text == "ℹ️ Инфо")
async def info(message: types.Message):
    await message.answer(
        "📌 О сервисе:\n"
        "— Высокоскоростные серверы в 5 странах\n"
        "— Протоколы: VLESS, Shadowsocks, WireGuard\n"
        "— Защита от утечек DNS и IPv6\n"
        "— Круглосуточная поддержка\n\n"
        "По вопросам: @support_username"
    )