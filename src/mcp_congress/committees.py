import json
from typing import Any

from .client import get_client


async def _fetch_committee(chamber: str, committee_code: str) -> dict[str, Any]:
    return await get_client().get(f"committee/{chamber.lower()}/{committee_code.lower()}", {})


async def search_committees(
    chamber: str | None = None,
    name: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> str:
    """Search for congressional committees by chamber (House/Senate) or name."""
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if chamber is not None:
        params["chamber"] = chamber
    if name is not None:
        params["query"] = name
    return json.dumps(await get_client().get("committee", params))


async def get_committee(chamber: str, committee_code: str) -> str:
    """Get committee details and membership. Chamber: 'house' or 'senate'. Code example: 'hspw00'."""
    return json.dumps(await _fetch_committee(chamber, committee_code))
