# tests/test_shutdown.py
"""Проверка трекинга и отмены fire-and-forget задач ЮKassa."""

import asyncio

import pytest

from services import payment_yookassa as yk


@pytest.fixture(autouse=True)
def clean_tasks():
    yk._pending_key_tasks.clear()
    yield
    yk._pending_key_tasks.clear()


@pytest.mark.asyncio
async def test_schedule_tracks_task():
    async def dummy():
        await asyncio.sleep(10)

    task = yk._schedule_key_task(dummy())
    assert task in yk._pending_key_tasks

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_shutdown_cancels_tasks():
    started = []

    async def long_task():
        started.append(1)
        await asyncio.sleep(100)

    task1 = yk._schedule_key_task(long_task())
    task2 = yk._schedule_key_task(long_task())

    await asyncio.sleep(0)  # дать задачам стартовать
    assert len(started) == 2

    await yk.shutdown_pending_tasks(timeout=1.0)

    assert task1.done()
    assert task2.done()
    assert len(yk._pending_key_tasks) == 0


@pytest.mark.asyncio
async def test_shutdown_empty_does_not_crash():
    await yk.shutdown_pending_tasks()
    assert len(yk._pending_key_tasks) == 0


@pytest.mark.asyncio
async def test_completed_task_removed_from_set():
    async def quick():
        return 42

    task = yk._schedule_key_task(quick())
    await task
    await asyncio.sleep(0)  # дать done_callback сработать
    assert task not in yk._pending_key_tasks


@pytest.mark.asyncio
async def test_shutdown_with_already_done_task():
    async def quick():
        return 1

    task = yk._schedule_key_task(quick())
    await task
    # shutdown не должен упасть на уже завершённых задачах
    await yk.shutdown_pending_tasks(timeout=1.0)