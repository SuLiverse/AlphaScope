from __future__ import annotations

import threading

import pytest

import backend.provider_timeout as provider_timeout


def test_call_with_timeout_returns_value():
    assert provider_timeout.call_with_timeout(lambda: 42, 1.0) == 42


def test_call_with_timeout_caps_inflight_threads(monkeypatch):
    semaphore = threading.BoundedSemaphore(1)
    semaphore.acquire()
    monkeypatch.setattr(provider_timeout, "_INFLIGHT", semaphore)

    with pytest.raises(TimeoutError, match="capacity exhausted"):
        provider_timeout.call_with_timeout(lambda: 42, 0.01, name="bounded-provider")

    semaphore.release()
