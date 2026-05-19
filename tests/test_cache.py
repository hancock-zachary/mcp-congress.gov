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


def _make_member_data(days_old: int) -> dict:
    dt = datetime.now(timezone.utc) - timedelta(days=days_old)
    return {"last_updated": dt.strftime("%Y-%m-%dT%H:%M:%SZ"), "members": {}}


def test_is_members_stale_returns_true_when_old(monkeypatch):
    monkeypatch.setattr(cache_mod, "load_members", lambda: _make_member_data(days_old=8))
    assert cache_mod.is_members_stale() is True


def test_is_members_stale_returns_false_when_fresh(monkeypatch):
    monkeypatch.setattr(cache_mod, "load_members", lambda: _make_member_data(days_old=3))
    assert cache_mod.is_members_stale() is False


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


def test_update_many_merges_existing_record(monkeypatch):
    existing = [{"congress": 119, "bill": "hr1", "policy_area": "Taxation"}]
    monkeypatch.setattr(cache_mod, "load", lambda: _make_data(0, existing.copy()))
    saved = {}
    monkeypatch.setattr(cache_mod, "save", lambda d: saved.update(d))

    cache_mod.update_many([{
        "congress": 119, "bill": "hr1", "policy_area": "Taxation",
        "sponsor_id": "A000001",
        "cosponsors": [],
    }])

    assert len(saved["bills"]) == 1
    assert saved["bills"][0]["sponsor_id"] == "A000001"


def test_build_cosponsor_index(monkeypatch):
    bills = [
        {
            "congress": 119, "bill": "hr1", "policy_area": "Transportation",
            "sponsor_id": "A000001",
            "cosponsors": [{"id": "B000002", "date": "2025-02-01"}],
        },
        {"congress": 118, "bill": "s2", "policy_area": "Taxation"},  # no sponsor data
    ]
    index = cache_mod.build_cosponsor_index({"bills": bills})
    assert "119hr1" in index
    assert index["119hr1"]["sponsor_id"] == "A000001"
    assert index["119hr1"]["cosponsors"][0]["id"] == "B000002"
    assert "118s2" not in index


async def test_refresh_fetches_and_persists(monkeypatch):
    recent_date = (datetime.now(timezone.utc) - timedelta(hours=25)).strftime("%Y-%m-%d")
    bills_page = {
        "bills": [{
            **SAMPLE_BILL,
            "congress": 119,
            "type": "hr",
            "number": "5",
            "updateDate": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "latestAction": {"actionDate": recent_date, "text": "Introduced"},
        }],
        "pagination": {"count": 1},
    }
    detail = {"bill": {**SAMPLE_BILL, "congress": 119, "type": "hr", "number": "5", "policyArea": {"name": "Economics and Public Finance"}}}
    cosp_response = {"cosponsors": [{"bioguideId": "B000002", "fullName": "Rep. Bob", "party": "D", "state": "CA", "sponsorshipDate": "2025-02-01"}]}

    monkeypatch.setattr(cache_mod, "load", lambda: _make_data(25, []))
    monkeypatch.setattr(cache_mod, "load_members", lambda: _make_member_data(days_old=8))
    saved = {}
    saved_members = {}
    monkeypatch.setattr(cache_mod, "save", lambda d: saved.update(d))
    monkeypatch.setattr(cache_mod, "save_members", lambda d: saved_members.update(d))

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=bills_page)

    with patch("mcp_congress.bills._fetch_bill", AsyncMock(return_value=detail)), \
         patch("mcp_congress.bills._fetch_bill_cosponsors", AsyncMock(return_value=cosp_response)):
        count = await cache_mod.refresh(mock_client, congresses=[119])

    assert count == 1
    record = next(
        r for r in saved["bills"]
        if r["congress"] == 119 and r["bill"] == "hr5"
    )
    assert record["policy_area"] == "Economics and Public Finance"
    assert record["sponsor_id"] == "J000295"
    assert record["cosponsors"][0]["id"] == "B000002"
    assert record["cosponsors"][0]["date"] == "2025-02-01"
    assert "J000295" in saved_members.get("members", {})
    assert "B000002" in saved_members.get("members", {})


async def test_refresh_skips_stale_action_dates(monkeypatch):
    """Bills whose latestAction.actionDate predates last_updated are not enriched."""
    old_date = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%d")
    bills_page = {
        "bills": [{
            **SAMPLE_BILL,
            "congress": 119,
            "type": "hr",
            "number": "99",
            "updateDate": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "latestAction": {"actionDate": old_date, "text": "Introduced"},
        }],
        "pagination": {"count": 1},
    }

    monkeypatch.setattr(cache_mod, "load", lambda: _make_data(25, []))
    saved = {}
    monkeypatch.setattr(cache_mod, "save", lambda d: saved.update(d))

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=bills_page)

    with patch("mcp_congress.bills._fetch_bill", AsyncMock(return_value={})):
        count = await cache_mod.refresh(mock_client, congresses=[119])

    assert count == 0


async def test_refresh_stops_early_on_old_update_date(monkeypatch):
    """Pagination stops when updateDate falls below last_updated — no second page fetched."""
    stale_update = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    bills_page = {
        "bills": [{
            **SAMPLE_BILL,
            "congress": 119,
            "type": "hr",
            "number": "7",
            "updateDate": stale_update,
            "latestAction": {"actionDate": "2025-01-01", "text": "Introduced"},
        }],
        "pagination": {"count": 500},  # implies more pages exist
    }

    monkeypatch.setattr(cache_mod, "load", lambda: _make_data(25, []))
    saved = {}
    monkeypatch.setattr(cache_mod, "save", lambda d: saved.update(d))

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=bills_page)

    with patch("mcp_congress.bills._fetch_bill", AsyncMock(return_value={})):
        await cache_mod.refresh(mock_client, congresses=[119])

    # Only one API call should have been made (no second page)
    assert mock_client.get.call_count == 1
