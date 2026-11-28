"""Unit tests for the engine factory + fallback chain (AC-505, AC-506)."""
from __future__ import annotations

import pytest
from app.engines import factory
from app.engines.base import EngineError, TTSEngine


class _StubEngine(TTSEngine):
    def __init__(self, name, available=True):
        self._name = name
        self._available = available

    @property
    def name(self):
        return self._name

    @property
    def display_name(self):
        return self._name.title()

    def is_available(self):
        return self._available

    async def list_voices(self, language=None):
        return []

    async def synthesize(self, text, voice, rate=1.0, pitch=0.0):
        raise EngineError("stub")


@pytest.fixture()
def registry():
    """Snapshot the registry so tests can register stubs safely."""
    saved = dict(factory._REGISTRY)
    saved_order = list(factory._FALLBACK_ORDER)
    yield
    factory._REGISTRY.clear()
    factory._REGISTRY.update(saved)
    factory._FALLBACK_ORDER[:] = saved_order


def test_builtin_engines_registered():
    names = {e.name for e in factory.list_engines()}
    assert {"gemini", "edge"} <= names


def test_get_unknown_engine_raises():
    with pytest.raises(EngineError):
        factory.get_engine("does-not-exist")


def test_fallback_chain_requested_first_and_unavailable_skipped(registry):
    factory._REGISTRY.clear()
    factory.register(_StubEngine("gemini", available=False))
    factory.register(_StubEngine("edge", available=True))
    factory.register(_StubEngine("mock", available=True))
    chain = factory.fallback_chain("gemini")
    assert [e.name for e in chain] == ["edge", "mock"]


def test_fallback_chain_default_order(registry):
    factory._REGISTRY.clear()
    factory.register(_StubEngine("edge"))
    factory.register(_StubEngine("gemini"))
    chain = factory.fallback_chain(None)
    assert [e.name for e in chain] == ["gemini", "edge"]
