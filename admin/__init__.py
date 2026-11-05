from . import bot as _bot
from .bot import dp, error_log, send_admin_alert, shutdown, startup

__all__ = [
    # admin_bot / main_bot доступны через __getattr__ ниже, но в __all__
    # их не включаем — Pylance не умеет связывать __getattr__ с __all__.
    "dp",
    "error_log",
    "send_admin_alert",
    "shutdown",
    "startup",
]

def __getattr__(name: str):
    # admin_bot и main_bot переназначаются в startup()/run_all —
    # читаем актуальное значение из модуля admin.bot,
    # а не замороженную копию на момент импорта.
    if name == "admin_bot":
        return _bot.admin_bot
    if name == "main_bot":
        return _bot.main_bot
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
