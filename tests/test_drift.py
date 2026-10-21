import asyncio
import json
import math
import random
from unittest.mock import AsyncMock, Mock

import pytest

from location_switch.device import DeviceController, DeviceError
from location_switch.drift import DriftPath, EARTH_RADIUS_M
from location_switch import server
from test_app import client, headers


def meters(a, b):
    lat_a, lon_a, lat_b, lon_b = map(math.radians, (*a, *b))
    h = math.sin((lat_b-lat_a)/2)**2 + math.cos(lat_a)*math.cos(lat_b)*math.sin((lon_b-lon_a)/2)**2
    return 2*EARTH_RADIUS_M*math.asin(math.sqrt(min(1, max(0, h))))


@pytest.mark.parametrize('anchor', [(0, 0), (12, 45), (80, -30), (90, 0), (-90, 0), (0, 180), (0, -180)])
def test_path_stays_within_radius_and_small_step_at_poles_and_date_line(anchor):
    path = DriftPath(*anchor, 3, rng=random.Random(42))
    prior = anchor
    points = []
    for _ in range(1000):
        point = path.step()
        assert -90 <= point[0] <= 90 and -180 <= point[1] <= 180
        assert meters(anchor, point) <= 3.001
        assert meters(prior, point) <= 0.501
        points.append(point)
        prior = point
    assert meters(anchor, points[0]) > 0
    assert len(set(points)) > 990


@pytest.mark.parametrize('radius', [-1, 21, 'NaN', 'Infinity'])
def test_bad_radius_rejected_before_device_command(client, monkeypatch, radius):
    change = AsyncMock()
    monkeypatch.setattr(server.controller, 'change', change)
    response = client.post('/api/spoof', json={'udid':'test-device-0001', 'latitude':12, 'longitude':45, 'drift_radius_m':radius}, headers=headers())
    assert response.status_code == 422
    change.assert_not_awaited()


def test_radius_passed_to_session(client, monkeypatch):
    change = AsyncMock(return_value={'mode':'spoofed'})
    monkeypatch.setattr(server.controller, 'change', change)
    assert client.post('/api/spoof', json={'udid':'test-device-0001', 'latitude':12, 'longitude':45, 'drift_radius_m':3}, headers=headers()).status_code == 200
    assert change.call_args.kwargs == {'drift_radius_m':3}


def controller_with_worker(monkeypatch):
    controller = DeviceController()
    controller.udid = 'test-device-0001'
    controller.drift_interval = 0.01
    process = AsyncMock()
    process.returncode = None
    process.stdin.close = Mock()
    commands = []
    process.stdin.write = lambda data: commands.append(json.loads(data))
    controller.process = process
    monkeypatch.setattr(controller, '_read', AsyncMock(return_value={'ok':True}))
    return controller, commands


async def until(predicate):
    async def wait():
        while not predicate():
            await asyncio.sleep(0.001)
    await asyncio.wait_for(wait(), 2)


async def test_updates_reuse_worker_and_restore_stops_drift(monkeypatch):
    controller, commands = controller_with_worker(monkeypatch)
    try:
        result = await controller.change('test-device-0001', 'set', 12, 45, 'Test', drift_radius_m=3)
        assert result['drift']['active']
        await until(lambda: len(commands) >= 3)
        assert controller.destination['latitude'] == 12  # anchor stays fixed
        assert controller.position != {'latitude':12, 'longitude':45}
        result = await controller.change('test-device-0001', 'clear')
        assert not result['drift']['active'] and result['mode'] == 'real'
        count = len(commands)
        await asyncio.sleep(0.04)
        assert len(commands) == count
        assert commands[-1]['action'] == 'clear'
    finally:
        await controller.shutdown()
    assert not controller.drift_tasks


async def test_restore_consumes_pending_drift_reply_before_clear(monkeypatch):
    controller, commands = controller_with_worker(monkeypatch)
    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0
    async def read():
        nonlocal calls
        calls += 1
        if calls == 2:
            entered.set()
            await release.wait()
        return {'ok':True}
    monkeypatch.setattr(controller, '_read', read)
    try:
        await controller.change('test-device-0001', 'set', 12, 45, drift_radius_m=3)
        await asyncio.wait_for(entered.wait(), 2)
        restore = asyncio.create_task(controller.change('test-device-0001', 'clear'))
        await asyncio.sleep(0)
        assert not restore.done()
        release.set()
        await restore
        assert commands[-1]['action'] == 'clear'
        count = len(commands)
        await asyncio.sleep(0.04)
        assert len(commands) == count
    finally:
        release.set()
        await controller.shutdown()


async def test_drift_failure_sets_unknown_and_closes_worker(monkeypatch):
    controller, commands = controller_with_worker(monkeypatch)
    close = AsyncMock()
    monkeypatch.setattr(controller, '_close', close)
    await controller.change('test-device-0001', 'set', 12, 45, drift_radius_m=3)
    monkeypatch.setattr(controller, '_read', AsyncMock(side_effect=DeviceError('Disconnected')))
    await until(lambda: controller.mode == 'unknown')
    assert not controller.status()['drift']['active']
    assert 'Disconnected' in controller.error
    await until(lambda: not controller.drift_tasks)
    close.assert_awaited_once()


async def test_reapply_without_drift_and_shutdown_stop_all_updates(monkeypatch):
    controller, commands = controller_with_worker(monkeypatch)
    await controller.change('test-device-0001', 'set', 12, 45, drift_radius_m=3)
    await until(lambda: len(commands) >= 2)
    await controller.change('test-device-0001', 'set', 12, 45, drift_radius_m=0)
    count = len(commands)
    await asyncio.sleep(0.04)
    assert len(commands) == count and not controller.status()['drift']['active']
    await controller.change('test-device-0001', 'set', 12, 45, drift_radius_m=3)
    await controller.shutdown()
    count = len(commands)
    await asyncio.sleep(0.04)
    assert len(commands) == count and commands[-1]['action'] == 'clear'
    assert not controller.drift_tasks
