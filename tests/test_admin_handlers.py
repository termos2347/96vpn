# tests/test_admin_handlers.py
"""Регрессионные тесты на регистрацию админ-команд.

Если кто-то забудет @dp.message(Command("grant")) — этот тест упадёт.

ВАЖНО: тесты НЕ интроспектируют FilterObject/Command. Структура
фильтров может меняться между версиями aiogram 3.x и ломаться на новых
Python. Проверяем handler.callback.__name__ — это стабильно.
"""

import pytest

from admin import bot as admin_module
from admin.bot import dp


# Ожидаемые функции-команды. Каждая должна иметь
# @dp.message(Command("имя_команды")) и попасть в dp.message.handlers.
EXPECTED_FUNCTIONS = {
    "cmd_start": "start",
    "cmd_menu": "menu",
    "cmd_health": "health",
    "cmd_errors": "errors",
    "cmd_grant": "grant",
    "cmd_revoke": "revoke",
    "cmd_stats": "stats",
    "cmd_broadcast": "broadcast",
    "cmd_broadcast_media": "broadcast_media",
    "cmd_userinfo": "userinfo",
    "cmd_show_yookassa_ips": "yookassa_ips",
    "cmd_set_yookassa_ips": "set_yookassa_ips",
}


def _registered_callback_names() -> set[str]:
    """Имена callback-функций, зарегистрированных в dp.message.

    Использует handler.callback.__name__, а не интроспекцию filters —
    это работает независимо от внутреннего формата FilterObject.
    """
    names: set[str] = set()
    for handler in dp.message.handlers:
        cb = getattr(handler, "callback", None)
        if cb is None:
            continue
        name = getattr(cb, "__name__", None)
        if name:
            names.add(name)
    return names


def test_dp_message_has_handlers():
    """Sanity: dp.message.handlers должен быть непустым после импорта.

    Если этот тест падает с 'dp.message.handlers = 0' — значит
    декораторы @dp.message(Command(...)) не применились. Проверьте
    admin/bot.py.
    """
    n = len(dp.message.handlers)
    names = sorted(_registered_callback_names())
    # Диагностика при падении — сразу видно что зарегистрировано
    assert n > 0, (
        f"dp.message.handlers = {n} (пусто). "
        f"В admin/bot.py отсутствуют декораторы "
        f"@dp.message(Command(...)) — либо импорт модуля сломан. "
        f"Зарегистрированные callback'и: {names}."
    )
    # Опционально: печатаем содержимое для отладки (pytest -s)
    print(f"\n[diag] dp.message.handlers = {n}")
    print(f"[diag] callbacks = {names}")


def test_all_admin_command_handlers_registered():
    """Все функции-команды зарегистрированы как callbacks в dp.message."""
    registered = _registered_callback_names()
    expected = set(EXPECTED_FUNCTIONS.keys())
    missing = expected - registered
    extra = registered - expected
    assert not missing, (
        f"Функции без @dp.message(Command(...))-декоратора: "
        f"{sorted(missing)}.\n"
        f"Все зарегистрированные: {sorted(registered)}.\n"
        f"Лишние (не в списке ожидаемых): {sorted(extra)}."
    )


@pytest.mark.parametrize(
    "func_name,command_name",
    sorted(EXPECTED_FUNCTIONS.items()),
    ids=[f"/{cmd}" for cmd in sorted(EXPECTED_FUNCTIONS.values())],
)
def test_individual_command_handler_registered(
    func_name: str, command_name: str
):
    """Гранулярный тест: при падении сразу видно, какой команды нет."""
    registered = _registered_callback_names()
    assert func_name in registered, (
        f"Команда /{command_name} не зарегистрирована: функция "
        f"{func_name} отсутствует в dp.message.handlers. "
        f"Добавьте декоратор @dp.message(Command({command_name!r})) "
        f"в admin/bot.py перед async def {func_name}(...).\n"
        f"Зарегистрированы: {sorted(registered)}."
    )


def test_broadcast_callback_registered():
    """Хотя бы один callback-обработчик с фильтрами зарегистрирован."""
    has_callbacks = any(
        handler.filters for handler in dp.callback_query.handlers
    )
    assert has_callbacks, (
        "Нет callback-обработчиков с фильтрами в dp.callback_query. "
        "Проверьте @dp.callback_query(...) декораторы в admin/bot.py."
    )


def test_grant_revoke_callable_from_text():
    """Smoke: функции-команды существуют в модуле (независимо от декоратора)."""
    assert hasattr(admin_module, "cmd_grant"), "cmd_grant не определён"
    assert hasattr(admin_module, "cmd_revoke"), "cmd_revoke не определён"
    assert hasattr(admin_module, "cmd_stats"), "cmd_stats не определён"
    assert hasattr(admin_module, "cmd_broadcast"), "cmd_broadcast не определён"