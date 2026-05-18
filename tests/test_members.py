import json
import pytest
from mcp_congress.members import (
    search_members,
    get_member,
    get_member_sponsored_legislation,
    get_member_votes,
)
from tests.conftest import SAMPLE_MEMBER


async def test_search_members_by_state(mock_client):
    mock_client.get.return_value = {"members": [SAMPLE_MEMBER], "pagination": {"count": 1}}
    result = await search_members(state="OH")
    data = json.loads(result)
    assert data["members"][0]["bioguideId"] == "J000295"
    call_args = mock_client.get.call_args[0][1]
    assert call_args["stateCode"] == "OH"


async def test_search_members_by_party_and_chamber(mock_client):
    mock_client.get.return_value = {"members": [], "pagination": {"count": 0}}
    await search_members(party="R", chamber="House", current_only=True)
    call_args = mock_client.get.call_args[0][1]
    assert call_args["party"] == "R"
    assert call_args["chamber"] == "House"
    assert call_args["currentMember"] is True


async def test_get_member_returns_json(mock_client):
    mock_client.get.return_value = {"member": SAMPLE_MEMBER}
    result = await get_member(bioguide_id="J000295")
    data = json.loads(result)
    assert data["member"]["bioguideId"] == "J000295"
    mock_client.get.assert_called_with("member/J000295", {})


async def test_get_member_sponsored_legislation(mock_client):
    mock_client.get.return_value = {
        "sponsoredLegislation": [{"congress": 119, "number": "42", "type": "HR"}],
        "pagination": {"count": 1},
    }
    result = await get_member_sponsored_legislation(bioguide_id="J000295")
    data = json.loads(result)
    assert "sponsoredLegislation" in data


async def test_get_member_votes_aggregates_records(mock_client):
    mock_client.get.return_value = {
        "sponsoredLegislation": [
            {"congress": 119, "number": "1", "type": "HR", "title": "Test Bill"},
        ],
        "pagination": {"count": 1},
    }
    result = await get_member_votes(bioguide_id="J000295", congress=119)
    data = json.loads(result)
    assert "bioguide_id" in data
    assert data["bioguide_id"] == "J000295"
