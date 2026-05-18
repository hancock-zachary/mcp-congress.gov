import json
from typing import Any

from .client import get_client


async def _fetch_member(bioguide_id: str) -> dict[str, Any]:
    return await get_client().get(f"member/{bioguide_id}", {})


async def _fetch_member_sponsored_legislation(
    bioguide_id: str, limit: int = 20, offset: int = 0
) -> dict[str, Any]:
    return await get_client().get(
        f"member/{bioguide_id}/sponsored-legislation",
        {"limit": limit, "offset": offset},
    )


async def _fetch_member_cosponsored_legislation(
    bioguide_id: str, limit: int = 20, offset: int = 0
) -> dict[str, Any]:
    return await get_client().get(
        f"member/{bioguide_id}/cosponsored-legislation",
        {"limit": limit, "offset": offset},
    )


async def search_members(
    name: str | None = None,
    state: str | None = None,
    party: str | None = None,
    chamber: str | None = None,
    current_only: bool = False,
    limit: int = 20,
    offset: int = 0,
) -> str:
    """Search for members of Congress by name, state (two-letter code), party (R/D/I), or chamber (House/Senate)."""
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if name is not None:
        params["query"] = name
    if state is not None:
        params["stateCode"] = state.upper()
    if party is not None:
        params["party"] = party
    if chamber is not None:
        params["chamber"] = chamber
    if current_only:
        params["currentMember"] = True
    return json.dumps(await get_client().get("member", params))


async def get_member(bioguide_id: str) -> str:
    """Get detailed biography, terms, and contact info for a member by BioGuide ID (e.g. 'J000295')."""
    return json.dumps(await _fetch_member(bioguide_id))


async def get_member_sponsored_legislation(
    bioguide_id: str, limit: int = 20, offset: int = 0
) -> str:
    """Get bills sponsored or introduced by a member."""
    return json.dumps(
        await _fetch_member_sponsored_legislation(bioguide_id, limit, offset)
    )


async def get_member_votes(bioguide_id: str, congress: int = 119, limit: int = 20) -> str:
    """Get a summary of a member's voting activity based on their sponsored and cosponsored legislation."""
    sponsored = await _fetch_member_sponsored_legislation(bioguide_id, limit=limit)
    cosponsored = await _fetch_member_cosponsored_legislation(bioguide_id, limit=limit)

    return json.dumps({
        "bioguide_id": bioguide_id,
        "congress": congress,
        "sponsored_legislation": sponsored.get("sponsoredLegislation", []),
        "cosponsored_legislation": cosponsored.get("cosponsoredLegislation", []),
        "note": "For specific roll call vote records, use get_bill_votes with individual bill identifiers.",
    })
