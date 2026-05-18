import pytest
import respx
import httpx
from mcp_congress.client import CongressClient


@pytest.fixture
def client():
    return CongressClient(api_key="test-key")


@respx.mock
async def test_get_success(client):
    respx.get("https://api.congress.gov/v3/bill").mock(
        return_value=httpx.Response(200, json={"bills": [], "pagination": {"count": 0}})
    )
    result = await client.get("bill", {"congress": 119})
    assert result == {"bills": [], "pagination": {"count": 0}}


@respx.mock
async def test_get_404_returns_structured_error(client):
    respx.get("https://api.congress.gov/v3/bill/99/hr/9999").mock(
        return_value=httpx.Response(404)
    )
    result = await client.get("bill/99/hr/9999")
    assert result["error"] == "not_found"
    assert "message" in result


@respx.mock
async def test_get_429_returns_rate_limited(client):
    respx.get("https://api.congress.gov/v3/bill").mock(
        return_value=httpx.Response(429)
    )
    result = await client.get("bill")
    assert result["error"] == "rate_limited"
    assert "message" in result


@respx.mock
async def test_caching_prevents_duplicate_requests(client):
    respx.get("https://api.congress.gov/v3/member").mock(
        return_value=httpx.Response(200, json={"members": []})
    )
    await client.get("member", {"stateCode": "TX"})
    await client.get("member", {"stateCode": "TX"})
    assert respx.calls.call_count == 1


@respx.mock
async def test_different_params_are_not_cached_together(client):
    respx.get("https://api.congress.gov/v3/member").mock(
        return_value=httpx.Response(200, json={"members": []})
    )
    await client.get("member", {"stateCode": "TX"})
    await client.get("member", {"stateCode": "CA"})
    assert respx.calls.call_count == 2
