# tests/test_ip_filter.py
"""Тесты IP-фильтра ЮKassa. Один битый CIDR в yookassa_ip.json
не должен ни ломать валидные записи, ни блокировать всё подряд."""

import pytest

from config import settings
from internal_api import ip_in_network


@pytest.fixture
def trusted_ips(monkeypatch):
    ips = [
        "185.71.76.0/24",
        "185.71.77.0/24",
        "77.75.153.0/25",
        "77.75.154.128/25",
        "77.75.156.11",
        "77.75.156.35",
        "2a02:5180::/32",
        "127.0.0.1",
    ]
    monkeypatch.setattr(settings, "YOOKASSA_TRUSTED_IPS", ips)
    return ips


def test_ipv4_in_cidr(trusted_ips):
    assert ip_in_network("185.71.76.5") is True
    assert ip_in_network("185.71.76.255") is True
    assert ip_in_network("185.71.77.100") is True


def test_ipv4_not_in_cidr(trusted_ips):
    assert ip_in_network("185.71.78.5") is False
    assert ip_in_network("10.0.0.1") is False


def test_exact_ip(trusted_ips):
    assert ip_in_network("77.75.156.11") is True
    assert ip_in_network("77.75.156.35") is True
    assert ip_in_network("77.75.156.12") is False


def test_half_cidr(trusted_ips):
    # /25 — 77.75.153.0 .. 77.75.153.127
    assert ip_in_network("77.75.153.0") is True
    assert ip_in_network("77.75.153.127") is True
    assert ip_in_network("77.75.153.128") is False


def test_ipv6_in_ipv6_cidr(trusted_ips):
    assert ip_in_network("2a02:5180::1") is True
    assert ip_in_network("2a02:5180:ffff::1") is True


def test_ipv6_not_in_ipv6_cidr(trusted_ips):
    assert ip_in_network("2a02:5181::1") is False


def test_ipv4_not_confused_with_ipv6(trusted_ips):
    # 127.0.0.1 — IPv4, в 2a02:5180::/32 его нет
    assert ip_in_network("127.0.0.1") is True  # но есть отдельной записью
    assert ip_in_network("::1") is False  # ::1 нет в списке


def test_invalid_ip_string(trusted_ips):
    assert ip_in_network("not-an-ip") is False
    assert ip_in_network("") is False
    assert ip_in_network("999.999.999.999") is False


def test_malformed_cidr_does_not_crash(monkeypatch):
    # "1.2.3.4/24" — strict=False исправит на 1.2.3.0/24
    monkeypatch.setattr(
        settings, "YOOKASSA_TRUSTED_IPS", ["1.2.3.4/24", "185.71.76.0/24"]
    )
    assert ip_in_network("1.2.3.5") is True
    assert ip_in_network("1.2.4.5") is False
    assert ip_in_network("185.71.76.5") is True


def test_garbage_cidr_ignored(monkeypatch):
    monkeypatch.setattr(
        settings, "YOOKASSA_TRUSTED_IPS", ["not-a-cidr", "185.71.76.0/24"]
    )
    # валидная запись по-прежнему работает
    assert ip_in_network("185.71.76.5") is True
    assert ip_in_network("10.0.0.1") is False