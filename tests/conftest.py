import pytest
from unittest.mock import AsyncMock, MagicMock


SAMPLE_BILL = {
    "congress": 119,
    "type": "HR",
    "number": "1",
    "title": "Infrastructure Investment Act",
    "introducedDate": "2025-01-15",
    "originChamber": "House",
    "latestAction": {"actionDate": "2025-03-01", "text": "Passed House."},
    "sponsor": {
        "bioguideId": "J000295",
        "fullName": "Rep. Jane Smith",
        "state": "OH",
        "party": "R",
    },
    "policyArea": {"name": "Transportation and Public Works"},
}

SAMPLE_MEMBER = {
    "bioguideId": "J000295",
    "directOrderName": "Jane Smith",
    "state": "Ohio",
    "party": "Republican",
    "chamber": "House of Representatives",
    "terms": {"item": [{"startYear": 2019, "endYear": 2025, "chamber": "House of Representatives"}]},
}


@pytest.fixture
def mock_client(monkeypatch):
    client = MagicMock()
    client.get = AsyncMock()
    for module in ("mcp_congress.bills", "mcp_congress.members", "mcp_congress.committees"):
        try:
            monkeypatch.setattr(f"{module}.get_client", lambda: client)
        except ImportError:
            pass
    return client
