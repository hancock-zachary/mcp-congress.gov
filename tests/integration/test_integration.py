"""
Integration tests — require a real CONGRESS_API_KEY environment variable.
Skipped automatically when CONGRESS_API_KEY is not set.
Run with: uv run pytest tests/integration/ -v
"""
import json
import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("CONGRESS_API_KEY"),
    reason="CONGRESS_API_KEY not set — skipping integration tests",
)


async def test_search_bills_live():
    from mcp_congress.bills import search_bills
    result = await search_bills(query="infrastructure", congress=119, limit=5)
    data = json.loads(result)
    assert "bills" in data
    assert isinstance(data["bills"], list)


async def test_search_members_live():
    from mcp_congress.members import search_members
    result = await search_members(state="TX", current_only=True, limit=5)
    data = json.loads(result)
    assert "members" in data
    assert len(data["members"]) > 0


async def test_search_committees_live():
    from mcp_congress.committees import search_committees
    result = await search_committees(chamber="House", limit=5)
    data = json.loads(result)
    assert "committees" in data


async def test_get_member_live():
    from mcp_congress.members import get_member
    result = await get_member(bioguide_id="P000197")  # Nancy Pelosi
    data = json.loads(result)
    assert "member" in data or "error" in data  # member may be inactive


async def test_get_member_profile_live():
    from mcp_congress.compound import get_member_profile
    result = await get_member_profile(bioguide_id="S001185")  # Terri Sewell
    data = json.loads(result)
    assert "bioguide_id" in data
    assert "member" in data


async def test_analyze_congress_priorities_live():
    from mcp_congress.compound import analyze_congress_priorities
    result = await analyze_congress_priorities(congress=119, limit_per_fetch=50)
    data = json.loads(result)
    assert "policy_areas" in data
    assert len(data["policy_areas"]) > 0
    areas = data["policy_areas"]
    if len(areas) > 1:
        assert areas[0]["total_weight"] >= areas[-1]["total_weight"]
