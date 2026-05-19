import json
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import mcp_congress.cache as cache_mod
from tests.conftest import SAMPLE_BILL


def _make_data(hours_old: int, bills: dict = None) -> dict:
    dt = datetime.now(timezone.utc) - timedelta(hours=hours_old)
    return {
        "last_updated": dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "bills": bills or {},
    }


def test_is_stale_returns_true_when_old(monkeypatch):
    monkeypatch.setattr(cache_mod, "load", lambda: _make_data(hours_old=25))
    assert cache_mod.is_stale() is True


def test_is_stale_returns_false_when_fresh(monkeypatch):
    monkeypatch.setattr(cache_mod, "load", lambda: _make_data(hours_old=1))
    assert cache_mod.is_stale() is False


def test_get_policy_area_hit(monkeypatch):
    monkeypatch.setattr(cache_mod, "load", lambda: _make_data(0, {"119hr1": "Transportation"}))
    assert cache_mod.get_policy_area("119hr1") == "Transportation"


def test_get_policy_area_miss(monkeypatch):
    monkeypatch.setattr(cache_mod, "load", lambda: _make_data(0, {}))
    assert cache_mod.get_policy_area("119hr999") is None


def test_update_many_merges_and_saves(monkeypatch):
    state = {"data": _make_data(0, {"119hr1": "Taxation"})}
    monkeypatch.setattr(cache_mod, "load", lambda: state["data"])
    saved = {}

    def fake_save(d):
        saved.update(d)

    monkeypatch.setattr(cache_mod, "save", fake_save)
    cache_mod.update_many({"119hr2": "Transportation"})
    assert saved["bills"]["119hr1"] == "Taxation"
    assert saved["bills"]["119hr2"] == "Transportation"


async def test_refresh_fetches_and_persists(monkeypatch):
    bills_page = {
        "bills": [{**SAMPLE_BILL, "congress": 119, "type": "hr", "number": "5"}],
        "pagination": {"count": 1},
    }
    detail = {"bill": {**SAMPLE_BILL, "type": "hr", "number": "5", "policyArea": {"name": "Economics and Public Finance"}}}

    monkeypatch.setattr(cache_mod, "load", lambda: _make_data(25, {}))
    saved = {}
    monkeypatch.setattr(cache_mod, "save", lambda d: saved.update(d))

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=bills_page)

    with patch("mcp_congress.bills._fetch_bill", AsyncMock(return_value=detail)):
        count = await cache_mod.refresh(mock_client, congresses=[119])

    assert count == 1
    assert saved["bills"].get("hr5") == "Economics and Public Finance"
