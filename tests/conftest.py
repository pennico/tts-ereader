"""Root test conftest.

The cloud sandbox ships a broken (empty) mistralai package while the v0
scripts import Mistral at module level. When the real SDK is not importable
we install a stub module so the v0 scripts can be imported and their logic
tested. The stub never makes network calls; no test here uses a real key.
"""
from __future__ import annotations

import sys
import types

try:
    from mistralai import Mistral
except Exception:
    try:  # mistralai 2.x: client moved off the top level
        from mistralai.client import Mistral
    except Exception:
        stub = types.ModuleType("mistralai")

        class _Mistral:
            def __init__(self, *args, **kwargs):
                raise RuntimeError("mistralai is stubbed in this environment")

        stub.Mistral = _Mistral
        sys.modules["mistralai"] = stub
