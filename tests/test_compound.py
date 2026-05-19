import json
import pytest
from unittest.mock import AsyncMock, patch
from mcp_congress.compound import (
    get_member_profile,
    get_member_stance,
    compare_member_alignment,
)
from tests.conftest import SAMPLE_MEMBER, SAMPLE_BILL


@pytest.fixture
def mock_member_fetches(monkeypatch):
    monkeypatch.setattr(
        "mcp_congress.compound._fetch_member",
        AsyncMock(return_value={"member": SAMPLE_MEMBER}),
    )
    monkeypatch.setattr(
        "mcp_congress.compound._fetch_member_sponsored_legislation",
        AsyncMock(return_value={"sponsoredLegislation": [SAMPLE_BILL], "pagination": {"count": 1}}),
    )
    monkeypatch.setattr(
        "mcp_congress.compound._fetch_member_cosponsored_legislation",
        AsyncMock(return_value={"cosponsoredLegislation": [], "pagination": {"count": 0}}),
    )


async def test_get_member_profile_returns_unified_dict(mock_member_fetches):
    result = await get_member_profile(bioguide_id="J000295")
    data = json.loads(result)
    assert data["bioguide_id"] == "J000295"
    assert "member" in data
    assert "sponsored_legislation" in data
    assert "cosponsored_legislation" in data


async def test_get_member_profile_fires_fetches_concurrently(mock_member_fetches):
    import asyncio
    original_gather = asyncio.gather
    gather_calls = []

    async def tracking_gather(*coros):
        gather_calls.append(len(coros))
        return await original_gather(*coros)

    with patch("mcp_congress.compound.asyncio.gather", side_effect=tracking_gather):
        await get_member_profile(bioguide_id="J000295")

    assert len(gather_calls) > 0, "asyncio.gather was not called"


async def test_get_member_stance_returns_structured_result(mock_member_fetches):
    result = await get_member_stance(bioguide_id="J000295", topic="transportation")
    data = json.loads(result)
    assert data["bioguide_id"] == "J000295"
    assert data["topic"] == "transportation"
    assert "sponsored_relevant" in data
    assert "cosponsored_relevant" in data


@pytest.fixture
def mock_two_members(monkeypatch):
    member_a = {**SAMPLE_MEMBER, "bioguideId": "A000001", "directOrderName": "Alice A"}
    member_b = {**SAMPLE_MEMBER, "bioguideId": "B000002", "directOrderName": "Bob B"}
    bill_a = {**SAMPLE_BILL, "number": "100"}
    bill_b = {**SAMPLE_BILL, "number": "200"}

    call_count = {"n": 0}

    async def alternating_sponsored(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] % 2 == 1:
            return {"sponsoredLegislation": [bill_a], "pagination": {"count": 1}}
        return {"sponsoredLegislation": [bill_b], "pagination": {"count": 1}}

    monkeypatch.setattr("mcp_congress.compound._fetch_member", AsyncMock(side_effect=[
        {"member": member_a}, {"member": member_b}
    ]))
    monkeypatch.setattr(
        "mcp_congress.compound._fetch_member_sponsored_legislation",
        alternating_sponsored,
    )
    monkeypatch.setattr(
        "mcp_congress.compound._fetch_member_cosponsored_legislation",
        AsyncMock(return_value={"cosponsoredLegislation": [], "pagination": {"count": 0}}),
    )


async def test_compare_member_alignment_returns_both_members(mock_two_members):
    result = await compare_member_alignment(
        bioguide_id_a="A000001", bioguide_id_b="B000002"
    )
    data = json.loads(result)
    assert "member_a" in data
    assert "member_b" in data
    assert "shared_policy_areas" in data


from mcp_congress.compound import (
    analyze_bill_support,
    suggest_cosponsor_opportunities,
    analyze_congress_priorities,
)


@pytest.fixture
def mock_bill_fetches(monkeypatch):
    monkeypatch.setattr(
        "mcp_congress.compound._fetch_bill",
        AsyncMock(return_value={"bill": {**SAMPLE_BILL, "committees": {"item": [{"systemCode": "hspw00"}]}}}),
    )
    monkeypatch.setattr(
        "mcp_congress.compound._fetch_bill_cosponsors",
        AsyncMock(return_value={"cosponsors": [{"bioguideId": "A000001", "fullName": "Rep. A", "party": "R", "state": "OH"}], "pagination": {"count": 1}}),
    )
    monkeypatch.setattr(
        "mcp_congress.compound._fetch_member_sponsored_legislation",
        AsyncMock(return_value={"sponsoredLegislation": [SAMPLE_BILL], "pagination": {"count": 1}}),
    )
    monkeypatch.setattr(
        "mcp_congress.compound._fetch_member_cosponsored_legislation",
        AsyncMock(return_value={"cosponsoredLegislation": [], "pagination": {"count": 0}}),
    )


async def test_analyze_bill_support_returns_support_data(mock_bill_fetches):
    result = await analyze_bill_support(congress=119, bill_type="hr", bill_number="1")
    data = json.loads(result)
    assert "bill" in data
    assert "cosponsors" in data
    assert "cosponsor_count" in data


async def test_suggest_cosponsor_opportunities_returns_ranked_list(mock_member_fetches, monkeypatch):
    monkeypatch.setattr(
        "mcp_congress.compound._search_bills_raw",
        AsyncMock(return_value={"bills": [
            {**SAMPLE_BILL, "number": "999", "title": "New Infrastructure Bill"},
        ], "pagination": {"count": 1}}),
    )
    result = await suggest_cosponsor_opportunities(bioguide_id="J000295", congress=119)
    data = json.loads(result)
    assert "bioguide_id" in data
    assert "suggestions" in data
    assert isinstance(data["suggestions"], list)


async def test_analyze_congress_priorities_tiers_by_advancement(monkeypatch):
    bills = [
        {**SAMPLE_BILL, "number": "1", "latestAction": {"text": "Became Public Law."}, "policyArea": {"name": "Transportation and Public Works"}},
        {**SAMPLE_BILL, "number": "2", "latestAction": {"text": "Referred to committee."}, "policyArea": {"name": "Transportation and Public Works"}},
        {**SAMPLE_BILL, "number": "3", "latestAction": {"text": "Passed House."}, "policyArea": {"name": "Economics and Public Finance"}},
    ]
    # All bills have policyArea so no detail fetches are triggered; count == len(bills) so no extra pages.
    monkeypatch.setattr(
        "mcp_congress.compound._search_bills_raw",
        AsyncMock(return_value={"bills": bills, "pagination": {"count": 3}}),
    )
    monkeypatch.setattr(
        "mcp_congress.compound._fetch_bill",
        AsyncMock(return_value={"bill": {}}),
    )
    # Cache is fresh — skip refresh; return empty bills dict so cache lookup is a no-op
    monkeypatch.setattr("mcp_congress.compound.cache.is_stale", lambda: False)
    monkeypatch.setattr("mcp_congress.compound.cache.load", lambda: {"last_updated": "2026-01-01T00:00:00Z", "bills": {}})
    monkeypatch.setattr("mcp_congress.compound.cache.update_many", lambda _: None)

    result = await analyze_congress_priorities(congress=119)
    data = json.loads(result)
    assert data["congress"] == 119
    assert "policy_areas" in data
    assert "bills_analyzed" in data
    assert "total_available" in data
    assert "uncategorized_bills" in data
    areas = {pa["area"]: pa for pa in data["policy_areas"]}
    transport = areas["Transportation and Public Works"]
    assert transport["enacted_count"] >= 1
    finance = areas["Economics and Public Finance"]
    assert finance["floor_vote_count"] >= 1
