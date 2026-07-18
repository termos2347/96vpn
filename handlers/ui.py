# handlers/ui.py
"""
Единый модуль интерфейса бота.
Содержит все тексты сообщений и функции генерации клавиатур.
"""
from datetime import datetime, timezone
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from config import settings


# ---------- Тексты сообщений ----------
class Texts:
    """Все текстовые сообщения бота."""

    @staticmethod
    def main_menu(user_name: str, vpn_end: datetime | None) -> str:
        """Главное меню с приветствием и статусом подписки."""
        if vpn_end and vpn_end > datetime.now(timezone.utc):
            days_left = (vpn_end - datetime.now(timezone.utc)).days
            status = f"✅ активна до **{vpn_end.strftime('%d.%m.%Y')}** (осталось {days_left} дн.)"
        else:
            status = "❌ не активна"
        return (
            f"👋 Привет, {user_name}!\n\n"
            f"📅 Ваша VPN‑подписка: {status}\n\n"
            "Выберите действие в меню ниже:"
        )

    @staticmethod
    def tariff_selection() -> str:
        return "💳 Выберите тариф VPN:"

    @staticmethod
    def tariff_option(period: str, price_rub: float) -> str:
        names = {"1m": "1 месяц", "3m": "3 месяца", "6m": "6 месяцев"}
        return f"{names.get(period, period)} — {price_rub:.0f} ₽"

    @staticmethod
    def payment_methods() -> str:
        return "Выберите способ оплаты:"

    @staticmethod
    def payment_link(price: float, currency: str, period: str) -> str:
        return (
            f"💳 Ссылка для оплаты VPN ({period}, {price:.2f} {currency.upper()})\n\n"
            "После оплаты подписка активируется автоматически.\n"
            "Если вы уже оплачивали ранее, срок будет продлён."
        )

    @staticmethod
    def my_keys(link: str | None) -> str:
        if link:
            return (
                "🔑 Ваш VPN‑ключ:\n\n"
                f"`{link}`\n\n"
                "📲 **Инструкция по установке:**\n"
                "1. Скачайте приложение (V2RayNG, Shadowrocket или Nekoray).\n"
                "2. Нажмите «Импорт из буфера» или вставьте ссылку вручную.\n"
                "3. Подключитесь и наслаждайтесь!"
            )
        return "❌ У вас нет активных VPN‑ключей. Оформите подписку в разделе «Купить / Продлить VPN»."

    @staticmethod
    def help_info() -> str:
        return (
            "ℹ️ **Инструкция и поддержка**\n\n"
            "1. **Как подключиться?**\n"
            "   • Оплатите подписку в разделе «Купить / Продлить VPN».\n"
            "   • После оплаты нажмите «Мои Ключи» – получите ссылку.\n"
            "   • Импортируйте ссылку в VPN‑приложение (V2RayNG, Shadowrocket).\n\n"
            "2. **Проблемы с подключением?**\n"
            "   • Проверьте, что подписка активна (статус в главном меню).\n"
            "   • Попробуйте перезапустить приложение или сменить сервер.\n\n"
            "3. **Связь с администратором**\n"
            f"   • @{settings.SUPPORT_USERNAME} (отвечаем в течение часа)."
        )

    @staticmethod
    def back_to_main() -> str:
        return "Возврат в главное меню..."

    @staticmethod
    def vpn_not_available() -> str:
        return "❌ VPN-сервис временно недоступен. Попробуйте позже."

    @staticmethod
    def no_active_subscription() -> str:
        return "❌ У вас нет активной VPN-подписки. Оформите её в разделе «Купить / Продлить VPN»."

    @staticmethod
    def payment_success(period: str, days: int) -> str:
        return f"✅ VPN подписка на {days} дней активирована!"

    @staticmethod
    def payment_already_processed() -> str:
        return "✅ Платёж уже обработан."

    @staticmethod
    def payment_error() -> str:
        return "❌ Ошибка при активации подписки. Обратитесь в поддержку."

    @staticmethod
    def key_creation_failed() -> str:
        return (
            "✅ Ваша VPN-подписка активирована, но не удалось создать ключ автоматически.\n"
            "Пожалуйста, нажмите «Мои Ключи» через минуту – ключ будет создан.\n"
            "Если проблема сохраняется, обратитесь в поддержку."
        )

    @staticmethod
    def key_creation_error() -> str:
        return (
            "✅ Подписка активирована, но произошла ошибка при создании ключа.\n"
            "Пожалуйста, нажмите «Мои Ключи» через минуту."
        )

    # ---- НОВЫЙ МЕТОД ДЛЯ ОПЛАТЫ ----
    @staticmethod
    def payment_success_with_date(vpn_end: datetime | None, days: int, link: str | None = None) -> str:
        """Сообщение об успешной оплате с указанием даты окончания."""
        now = datetime.now(timezone.utc)
        if vpn_end and vpn_end > now:
            date_str = vpn_end.strftime('%d.%m.%Y')
            msg = f"✅ Ваша VPN-подписка **продлена** до **{date_str}** (на {days} дней).\n\n"
        else:
            msg = f"✅ Ваша VPN-подписка активирована на {days} дней.\n\n"
        if link:
            msg += (
                f"🔗 Ваша ссылка для подключения:\n`{link}`\n\n"
                "Скопируйте её и вставьте в VPN-приложение (V2RayNG, Shadowrocket, Nekoray)."
            )
        else:
            msg += (
                "🔑 Мы автоматически создаём ключ, это может занять несколько минут. "
                "Как только ключ будет готов, мы пришлём его вам.\n\n"
                "Если через 10 минут ничего не пришло – нажмите кнопку «Мои Ключи»."
            )
        return msg


# ---------- Клавиатуры ----------
class Keyboards:
    """Все клавиатуры бота."""

    @staticmethod
    def main_menu() -> ReplyKeyboardMarkup:
        """Reply‑клавиатура главного меню."""
        buttons = [
            [KeyboardButton(text="🚀 Купить / Продлить VPN")],
            [KeyboardButton(text="🔑 Мои Ключи")],
            [KeyboardButton(text="ℹ️ Инструкция и Поддержка")]
        ]
        return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

    @staticmethod
    def tariff_selection() -> InlineKeyboardMarkup:
        """Inline‑клавиатура выбора тарифа (1, 3, 6 месяцев)."""
        buttons = []
        for period, days in settings.PERIOD_DAYS.items():
            price = settings.VPN_PRICES["rub"][period]
            label = f"{period_to_text(period)} — {price:.0f} ₽"
            callback = f"tariff_{period}"
            buttons.append([InlineKeyboardButton(text=label, callback_data=callback)])
        buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")])
        return InlineKeyboardMarkup(inline_keyboard=buttons)

    @staticmethod
    def payment_methods(period: str) -> InlineKeyboardMarkup:
        """Выбор способа оплаты для выбранного тарифа."""
        buttons = [
            [InlineKeyboardButton(text="🇷🇺 Рубли", callback_data=f"pay_{period}_rub")],
            [InlineKeyboardButton(text="⭐ Telegram Stars", callback_data=f"pay_{period}_stars")],
            [InlineKeyboardButton(text="₿ USDT (TRC20)", callback_data=f"pay_{period}_usdt")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_tariffs")]
        ]
        return InlineKeyboardMarkup(inline_keyboard=buttons)

    @staticmethod
    def back_to_main_inline() -> InlineKeyboardMarkup:
        """Простая кнопка «Назад» в главное меню."""
        return InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔙 Главное меню", callback_data="back_to_main")]]
        )

    @staticmethod
    def payment_url_button(url: str) -> InlineKeyboardMarkup:
        """Кнопка для перехода на страницу оплаты."""
        return InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="💳 Оплатить", url=url)]]
        )


# ---------- Вспомогательные функции ----------
def period_to_text(period: str) -> str:
    """Преобразует код периода в читаемый текст."""
    return {"1m": "1 месяц", "3m": "3 месяца", "6m": "6 месяцев"}.get(period, period)