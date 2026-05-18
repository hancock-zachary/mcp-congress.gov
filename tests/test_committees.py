import json
import pytest
from mcp_congress.committees import search_committees, get_committee


SAMPLE_COMMITTEE = {
    "systemCode": "hspw00",
    "name": "Committee on Transportation and Infrastructure",
    "chamber": "House",
    "committeeTypeCode": "Standing",
    "url": "https://api.congress.gov/v3/committee/house/hspw00",
}


async def test_search_committees_by_chamber(mock_client):
    mock_client.get.return_value = {"committees": [SAMPLE_COMMITTEE], "pagination": {"count": 1}}
    result = await search_committees(chamber="House")
    data = json.loads(result)
    assert data["committees"][0]["name"] == "Committee on Transportation and Infrastructure"
    call_args = mock_client.get.call_args[0][1]
    assert call_args["chamber"] == "House"


async def test_get_committee_returns_json(mock_client):
    mock_client.get.return_value = {"committee": SAMPLE_COMMITTEE}
    result = await get_committee(chamber="house", committee_code="hspw00")
    data = json.loads(result)
    assert data["committee"]["systemCode"] == "hspw00"
    mock_client.get.assert_called_with("committee/house/hspw00", {})
