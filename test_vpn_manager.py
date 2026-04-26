import pytest
import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch
from services.vpn_manager import VPNManager
from services.vpn_provider import XUIVPNProvider

@pytest.mark.asyncio
async def test_vpn_manager_initialization():
    """Тест инициализации VPNManager."""
    manager = VPNManager()
    assert manager is not None
    assert manager.provider is not None
    print("VPNManager инициализирован успешно")

@pytest.mark.asyncio
async def test_vpn_provider_initialization():
    """Тест инициализации XUIVPNProvider."""
    provider = XUIVPNProvider()
    assert provider is not None
    assert provider.base_url  # Проверяем что URL загружен
    assert provider.username  # Проверяем что имя загружено
    assert provider.inbound_id > 0
    assert provider.sub_port > 0
    print(f"XUIVPNProvider инициализирован: {provider.base_url}")
    await provider.close()

def test_config_loading():
    """Тест загрузки конфигурации."""
    from config import VPN_PRICES, BYPASS_PRICES, TOKEN, DATABASE_URL
    assert TOKEN  # Проверяем что токен есть
    assert DATABASE_URL  # Проверяем БД URL
    assert 'rub' in VPN_PRICES
    assert 'stars' in VPN_PRICES
    assert 'usdt' in VPN_PRICES
    assert '1m' in VPN_PRICES['rub']  # Проверяем структуру цен
    print(f"Конфигурация загружена успешно. VPN цены доступны: {list(VPN_PRICES.keys())}")

def test_vpn_prices_structure():
    """Тест структуры цен VPN."""
    from config import VPN_PRICES, BYPASS_PRICES
    
    # Проверяем структуру
    for currency, periods in VPN_PRICES.items():
        assert isinstance(periods, dict)
        assert '1m' in periods or '3m' in periods or '6m' in periods
        for period, price in periods.items():
            assert isinstance(price, (int, float))
            assert price > 0
    
    print("Структура цен VPN корректна")

if __name__ == "__main__":
    # Запуск тестов: pytest test_vpn_manager.py -v
    pass