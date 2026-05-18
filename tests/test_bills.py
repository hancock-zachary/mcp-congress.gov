import json
import pytest
from mcp_congress.bills import search_bills, get_bill, get_bill_cosponsors, get_bill_votes
from tests.conftest import SAMPLE_BILL


async def test_search_bills_returns_json(mock_client):
    mock_client.get.return_value = {"bills": [SAMPLE_BILL], "pagination": {"count": 1}}
    result = await search_bills(query="infrastructure", congress=119)
    data = json.loads(result)
    assert "bills" in data
    assert data["bills"][0]["title"] == "Infrastructure Investment Act"
    mock_client.get.assert_called_once()
    call_args = mock_client.get.call_args
    assert call_args[0][0] == "bill"
    assert call_args[0][1]["query"] == "infrastructure"
    assert call_args[0][1]["congress"] == 119


async def test_get_bill_returns_json(mock_client):
    mock_client.get.return_value = {"bill": SAMPLE_BILL}
    result = await get_bill(congress=119, bill_type="hr", bill_number="1")
    data = json.loads(result)
    assert data["bill"]["type"] == "HR"
    mock_client.get.assert_called_with("bill/119/hr/1", {"limit": 1})


async def test_get_bill_cosponsors_returns_json(mock_client):
    mock_client.get.return_value = {
        "cosponsors": [{"bioguideId": "A000001", "fullName": "Rep. A"}],
        "pagination": {"count": 1},
    }
    result = await get_bill_cosponsors(congress=119, bill_type="hr", bill_number="1")
    data = json.loads(result)
    assert "cosponsors" in data


async def test_get_bill_votes_returns_json(mock_client):
    mock_client.get.return_value = {
        "actions": {
            "items": [
                {
                    "actionDate": "2025-03-01",
                    "text": "Passed House.",
                    "recordedVotes": [
                        {
                            "chamber": "House",
                            "congress": 119,
                            "rollNumber": 42,
                            "url": "http://clerk.house.gov/evs/2025/roll042.xml",
                        }
                    ],
                }
            ]
        }
    }
    result = await get_bill_votes(congress=119, bill_type="hr", bill_number="1")
    data = json.loads(result)
    assert "recorded_votes" in data


async def test_search_bills_passes_optional_params(mock_client):
    mock_client.get.return_value = {"bills": [], "pagination": {"count": 0}}
    await search_bills(congress=119, bill_type="s", limit=10, offset=20)
    call_args = mock_client.get.call_args[0][1]
    assert call_args["billType"] == "s"
    assert call_args["limit"] == 10
    assert call_args["offset"] == 20
