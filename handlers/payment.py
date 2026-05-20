import logging
from datetime import datetime, timedelta, timezone
from aiogram import Router, F, types
from aiogram.enums import ParseMode
from aiogram.types import PreCheckoutQuery
from db.crud import (
    set_vpn_subscription, set_bypass_subscription,
    log_bot_payment, is_bot_payment_processed
)
from .keyboards import vpn_currency_keyboard, vpn_period_keyboard
from config import PAYMENT_LINK_TTL_MINUTES, VPN_PRICES, INTERNAL_API_SECRET, SITE_URL, ADMIN_CHAT_ID
from services.vpn_manager import VPNManager
from utils.decorators import rate_limit
from utils.validators import validate_user_id, validate_currency, ValidationError
from handlers import get_vpn_manager
import jwt

logger = logging.getLogger(__name__)

router = Router()
PERIOD_DAYS = {"1m": 30, "3m": 90, "6m": 180}

def create_payment_token(telegram_id: int, product_type: str, period: str, currency: str, amount: float) -> str:
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=PAYMENT_LINK_TTL_MINUTES)
    payload = {
        "telegram_id": telegram_id,
        "product_type": product_type,
        "period": period,
        "currency": currency,
        "amount": amount,
        "exp": int(exp.timestamp())
    }
    return jwt.encode(payload, INTERNAL_API_SECRET, algorithm="HS256")

# ---------- VPN Payment Handlers ----------
@router.message(F.text == "💳 Оплатить VPN")
@rate_limit(max_per_minute=10)
async def pay_vpn(message: types.Message):
    try:
        validate_user_id(message.from_user.id)
        await message.answer("💎 Выберите валюту для оплаты VPN:", reply_markup=vpn_currency_keyboard())
    except ValidationError as e:
        logger.warning(f"Validation error in pay_vpn: {e}")
        await message.answer("❌ Ошибка валидации. Попробуйте позже.")


@router.callback_query(F.data.startswith("vpn_currency_"))
@rate_limit(max_per_minute=10)
async def vpn_choose_period(callback: types.CallbackQuery):
    try:
        validate_user_id(callback.from_user.id)
        currency = callback.data.split("_")[-1]
        validate_currency(currency)
        await callback.message.edit_text(
            "📅 Выберите период подписки:",
            reply_markup=vpn_period_keyboard(currency)
        )
        await callback.answer()
    except ValidationError as e:
        logger.warning(f"Validation error in vpn_choose_period: {e}")
        await callback.answer("❌ Ошибка: некорректные данные", show_alert=True)


@router.callback_query(F.data == "vpn_back_to_currency")
@rate_limit(max_per_minute=10)
async def vpn_back_to_currency(callback: types.CallbackQuery):
    try:
        validate_user_id(callback.from_user.id)
        await callback.message.edit_text(
            "💎 Выберите валюту для оплаты VPN:",
            reply_markup=vpn_currency_keyboard()
        )
        await callback.answer()
    except ValidationError as e:
        logger.warning(f"Validation error in vpn_back_to_currency: {e}")
        await callback.answer("❌ Ошибка: некорректные данные", show_alert=True)


@router.callback_query(F.data.regexp(r"^vpn_(1m|3m|6m)_(rub|usdt)$"))
@rate_limit(max_per_minute=5)
async def vpn_payment_link(callback: types.CallbackQuery):
    _, period, currency = callback.data.split("_")
    telegram_id = callback.from_user.id
    price = VPN_PRICES[currency][period]

    try:
        token = create_payment_token(telegram_id, "vpn", period, currency, price)
        payment_url = f"{SITE_URL}/pay/subscription?token={token}"

        logger.info(f"💰 Payment link generated for user {telegram_id}: {payment_url} (period={period}, currency={currency}, price={price})")

        if ADMIN_CHAT_ID:
            try:
                await callback.bot.send_message(
                    ADMIN_CHAT_ID,
                    f"🔗 Ссылка на оплату VPN для пользователя {telegram_id}:\n{payment_url}\n\nПериод: {period}, Валюта: {currency}, Сумма: {price}"
                )
            except Exception as e:
                logger.error(f"Не удалось отправить ссылку админу: {e}")

    except Exception as e:
        logger.error(f"Failed to create payment token: {e}")
        await callback.answer("❌ Ошибка при формировании ссылки", show_alert=True)
        return

    await callback.message.delete()

    ttl_text = f"{PAYMENT_LINK_TTL_MINUTES} мин." if PAYMENT_LINK_TTL_MINUTES < 60 else f"{PAYMENT_LINK_TTL_MINUTES // 60} ч."
    msg = (
        f"💳 Для оплаты VPN <a href='{payment_url}'>нажмите здесь</a>\n"
        f"<i>Ссылка действительна {ttl_text}.</i>"
    )
    await callback.message.answer(
        text=msg,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )
    await callback.answer()

# ---------- Bypass Payment Handlers ----------
"""
@router.message(F.text == "💰 Оплатить обход")
@rate_limit(max_per_minute=10)
async def pay_bypass(message: types.Message):
    user_id = message.from_user.id
    if not await is_vpn_active(user_id):
        await message.answer(
            "❌ Для оплаты обхода блокировок необходима активная VPN-подписка.\n"
            "Сначала оплатите VPN в разделе 💳 Оплатить VPN."
        )
        return
    await message.answer("🔓 Выберите валюту для оплаты обхода блокировок:", reply_markup=bypass_currency_keyboard())


@router.callback_query(F.data.startswith("bypass_currency_"))
@rate_limit(max_per_minute=10)
async def bypass_choose_period(callback: types.CallbackQuery):
    currency = callback.data.split("_")[-1]
    await callback.message.edit_text(
        "📅 Выберите период подписки на обход:",
        reply_markup=bypass_period_keyboard(currency)
    )
    await callback.answer()


@router.callback_query(F.data == "bypass_back_to_currency")
@rate_limit(max_per_minute=10)
async def bypass_back_to_currency(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "🔓 Выберите валюту для оплаты обхода блокировок:",
        reply_markup=bypass_currency_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^bypass_(1m|3m)_(rub|usdt)$"))
@rate_limit(max_per_minute=5)
async def bypass_payment_link(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if not await is_vpn_active(user_id):
        await callback.answer("❌ Сначала оплатите основной VPN", show_alert=True)
        return

    _, period, currency = callback.data.split("_")
    price = BYPASS_PRICES[currency][period]

    try:
        token = create_payment_token(user_id, "bypass", period, currency, price)
        payment_url = f"{SITE_URL}/pay/subscription?token={token}"
        logger.info(f"Generated payment URL: {payment_url}")
    except Exception as e:
        logger.error(f"Failed to create payment token: {e}")
        await callback.answer("❌ Ошибка при формировании ссылки", show_alert=True)
        return

    await callback.message.delete()

    ttl_text = f"{PAYMENT_LINK_TTL_MINUTES} мин." if PAYMENT_LINK_TTL_MINUTES < 60 else f"{PAYMENT_LINK_TTL_MINUTES // 60} ч."
    msg = (
        f"🛡️ Для оплаты обхода DPI <a href='{payment_url}'>нажмите здесь</a>\n"
        f"<i>Ссылка действительна {ttl_text}.</i>"
    )

    await callback.message.answer(
        text=msg,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )
    await callback.answer()
"""
# ---------- Платежи Telegram Stars ----------
@router.pre_checkout_query()
async def pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await pre_checkout_query.answer(ok=True)


@router.message(F.successful_payment)
async def successful_payment(message: types.Message):
    payment = message.successful_payment
    payload = payment.invoice_payload          # "vpn_1m_123456"
    telegram_payment_id = payment.telegram_payment_charge_id
    logger.info(f"⭐ Successful Stars payment: payload={payload}, payment_id={telegram_payment_id}")

    # Идемпотентность
    if await is_bot_payment_processed(telegram_payment_id):
        logger.info(f"Duplicate Stars payment {telegram_payment_id} ignored")
        await message.answer("✅ Этот платёж уже был обработан.")
        return

    parts = payload.split("_")
    if len(parts) < 3:
        logger.error(f"Invalid invoice payload: {payload}")
        return
    product_type, period, user_id_str = parts[0], parts[1], parts[2]
    user_id = int(user_id_str)
    days = PERIOD_DAYS.get(period, 0)

    if product_type == "vpn":
        await set_vpn_subscription(user_id, days)
        await log_bot_payment(telegram_payment_id, user_id)

        # Создаём VPN‑ключ
        vpn_manager = get_vpn_manager()
        if vpn_manager:
            link = await vpn_manager.create_key(user_id, days)
            if link:
                await message.answer(f"✅ VPN подписка на {days} дней активирована!\n🔗 Ваша ссылка: {link}")
            else:
                await message.answer(f"✅ VPN подписка на {days} дней активирована, но ключ не создан. Обратитесь в поддержку.")
        else:
            await message.answer(f"✅ VPN подписка на {days} дней активирована!")
    elif product_type == "bypass":
        await set_bypass_subscription(user_id, days)
        await log_bot_payment(telegram_payment_id, user_id)
        await message.answer(f"✅ Обход на {days} дней активирован!")
    else:
        logger.warning(f"Unknown product type in Stars payment: {product_type}")