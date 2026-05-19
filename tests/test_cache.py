import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import mcp_congress.cache as cache_mod
from tests.conftest import SAMPLE_BILL


def _make_data(hours_old: int, bills: list = None) -> dict:
    dt = datetime.now(timezone.utc) - timedelta(hours=hours_old)
    return {
        "last_updated": dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "bills": bills or [],
    }


def test_is_stale_returns_true_when_old(monkeypatch):
    monkeypatch.setattr(cache_mod, "load", lambda: _make_data(hours_old=25))
    assert cache_mod.is_stale() is True


def test_is_stale_returns_false_when_fresh(monkeypatch):
    monkeypatch.setattr(cache_mod, "load", lambda: _make_data(hours_old=1))
    assert cache_mod.is_stale() is False


def test_build_index_returns_lookup_dict(monkeypatch):
    data = _make_data(0, [
        {"congress": 119, "bill": "hr1", "policy_area": "Transportation"},
        {"congress": 118, "bill": "hr1", "policy_area": "Taxation"},
    ])
    index = cache_mod.build_index(data)
    assert index["119hr1"] == "Transportation"
    assert index["118hr1"] == "Taxation"


def test_update_many_appends_new_records(monkeypatch):
    existing = [{"congress": 119, "bill": "hr1", "policy_area": "Taxation"}]
    monkeypatch.setattr(cache_mod, "load", lambda: _make_data(0, existing.copy()))
    saved = {}
    monkeypatch.setattr(cache_mod, "save", lambda d: saved.update(d))

    cache_mod.update_many([{"congress": 119, "bill": "hr2", "policy_area": "Transportation"}])

    assert len(saved["bills"]) == 2
    assert saved["bills"][0] == {"congress": 119, "bill": "hr1", "policy_area": "Taxation"}
    assert saved["bills"][1] == {"congress": 119, "bill": "hr2", "policy_area": "Transportation"}


def test_update_many_skips_duplicates(monkeypatch):
    existing = [{"congress": 119, "bill": "hr1", "policy_area": "Taxation"}]
    monkeypatch.setattr(cache_mod, "load", lambda: _make_data(0, existing.copy()))
    saved = {}
    monkeypatch.setattr(cache_mod, "save", lambda d: saved.update(d))

    cache_mod.update_many([{"congress": 119, "bill": "hr1", "policy_area": "Taxation"}])

    assert len(saved["bills"]) == 1


async def test_refresh_fetches_and_persists(monkeypatch):
    bills_page = {
        "bills": [{**SAMPLE_BILL, "congress": 119, "type": "hr", "number": "5"}],
        "pagination": {"count": 1},
    }
    detail = {"bill": {**SAMPLE_BILL, "congress": 119, "type": "hr", "number": "5", "policyArea": {"name": "Economics and Public Finance"}}}

    monkeypatch.setattr(cache_mod, "load", lambda: _make_data(25, []))
    saved = {}
    monkeypatch.setattr(cache_mod, "save", lambda d: saved.update(d))

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=bills_page)

    with patch("mcp_congress.bills._fetch_bill", AsyncMock(return_value=detail)):
        count = await cache_mod.refresh(mock_client, congresses=[119])

    assert count == 1
    assert any(
        r["congress"] == 119 and r["bill"] == "hr5" and r["policy_area"] == "Economics and Public Finance"
        for r in saved["bills"]
    )
