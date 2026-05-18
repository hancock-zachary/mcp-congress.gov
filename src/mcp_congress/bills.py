import json
from typing import Any

from .client import get_client


async def _fetch_bill(congress: int, bill_type: str, bill_number: str) -> dict[str, Any]:
    return await get_client().get(f"bill/{congress}/{bill_type.lower()}/{bill_number}", {"limit": 1})


async def _fetch_bill_actions(congress: int, bill_type: str, bill_number: str) -> dict[str, Any]:
    return await get_client().get(f"bill/{congress}/{bill_type.lower()}/{bill_number}/actions")


async def _fetch_bill_cosponsors(congress: int, bill_type: str, bill_number: str) -> dict[str, Any]:
    return await get_client().get(
        f"bill/{congress}/{bill_type.lower()}/{bill_number}/cosponsors"
    )


async def search_bills(
    query: str | None = None,
    congress: int | None = None,
    bill_type: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> str:
    """Search for bills by keyword, congress number, or bill type (hr, s, hjres, sjres, hres, sres)."""
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if congress is not None:
        params["congress"] = congress
    if bill_type is not None:
        params["billType"] = bill_type.lower()
    if query is not None:
        params["query"] = query
    return json.dumps(await get_client().get("bill", params))


async def get_bill(congress: int, bill_type: str, bill_number: str) -> str:
    """Get full details for a specific bill including actions, sponsor, and policy area."""
    return json.dumps(await _fetch_bill(congress, bill_type, bill_number))


async def get_bill_cosponsors(congress: int, bill_type: str, bill_number: str) -> str:
    """Get all cosponsors of a specific bill."""
    return json.dumps(await _fetch_bill_cosponsors(congress, bill_type, bill_number))


async def get_bill_votes(congress: int, bill_type: str, bill_number: str) -> str:
    """Get recorded floor votes for a bill, extracted from bill actions."""
    actions_data = await _fetch_bill_actions(congress, bill_type, bill_number)
    if "error" in actions_data:
        return json.dumps(actions_data)

    items = actions_data.get("actions", {}).get("items", [])
    recorded_votes = [
        {
            "action_date": item["actionDate"],
            "action_text": item["text"],
            "votes": item["recordedVotes"],
        }
        for item in items
        if item.get("recordedVotes")
    ]
    return json.dumps({"recorded_votes": recorded_votes, "bill": f"{bill_type.upper()} {bill_number}"})
