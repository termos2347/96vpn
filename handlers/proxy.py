from aiogram import Router, F, types

router = Router()

@router.message(F.text == "🆓 Прокси")
async def free_proxy(message: types.Message):
    # Замените IP и порт на реальные
    proxy_link = "tg://proxy?server=your_server_ip&port=443&secret=00000000000000000000000000000000"
    await message.answer(
        f"🆓 Бесплатный MTProto прокси для Telegram:\n"
        f"`{proxy_link}`\n\n"
        f"Нажмите на ссылку — Telegram сам предложит подключиться.",
        parse_mode="Markdown"
    )