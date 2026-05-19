"""
Seed the member cache with representative details (name, party, state).

Run this once (or whenever you want a fresh full seed) to pre-populate
src/mcp_congress/data/member_cache.json before committing to the repo.
Teammates who pull the repo get the benefit of these lookups without needing
to make any API calls themselves.

Usage:
    uv run python src/mcp_congress/seed/seed_members.py
    uv run python src/mcp_congress/seed/seed_members.py --congress 119
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv
load_dotenv()

from mcp_congress.client import CongressClient
from mcp_congress.cache import load_members, save_members

PAGE_SIZE = 250
CONCURRENT_PAGES = 5


async def fetch_all_members(client: CongressClient, congress: int | None) -> list[dict]:
    endpoint = f"member/{congress}" if congress else "member"
    first = await client.get(endpoint, {"limit": PAGE_SIZE, "offset": 0, "sort": "name"})
    if "error" in first:
        print(f"  Error fetching members: {first}")
        return []

    total = first.get("pagination", {}).get("count", 0)
    members = list(first.get("members", []))
    print(f"  {total} total members — fetching {max(0, (total - 1) // PAGE_SIZE)} more pages...")

    if total > PAGE_SIZE:
        offsets = list(range(PAGE_SIZE, total, PAGE_SIZE))
        for i in range(0, len(offsets), CONCURRENT_PAGES):
            chunk = offsets[i:i + CONCURRENT_PAGES]
            pages = await asyncio.gather(*[
                client.get(endpoint, {"limit": PAGE_SIZE, "offset": offset, "sort": "name"})
                for offset in chunk
            ])
            for page in pages:
                members.extend(page.get("members", []))
            print(f"  Fetched {min(len(members), total)}/{total} members")

    return members


_CHAMBER_MAP = {
    "house of representatives": "House",
    "senate": "Senate",
}


def _normalize(raw: dict) -> tuple[str, dict] | None:
    """Extract bioguide ID and normalized member record from a raw API member object.
    Returns None for inactive members (currentMember != True).
    """
    if not raw.get("currentMember"):
        return None
    bid = raw.get("bioguideId", "")
    if not bid:
        return None
    district = raw.get("district")
    chamber_raw = (raw.get("chamber") or "").lower()
    return bid, {
        "name": raw.get("directOrderName") or raw.get("invertedOrderName") or raw.get("name", ""),
        "party": raw.get("partyName", ""),
        "state": raw.get("state", ""),
        "chamber": _CHAMBER_MAP.get(chamber_raw, raw.get("chamber", "")),
        "district": int(district) if district is not None else None,
    }


async def main(congress: int | None) -> None:
    api_key = os.environ.get("CONGRESS_API_KEY")
    if not api_key:
        print("Error: CONGRESS_API_KEY environment variable is not set.")
        print("Add it to your .env file or export it before running this script.")
        sys.exit(1)

    client = CongressClient(api_key=api_key, timeout=60.0)
    existing = load_members().get("members", {})
    print(f"Existing member cache entries: {len(existing)}")

    scope = f"{congress}th Congress" if congress else "all congresses"
    print(f"\nFetching members for {scope}...")
    raw_members = await fetch_all_members(client, congress)

    new_records: dict[str, dict] = {}
    for raw in raw_members:
        result = _normalize(raw)
        if result and result[0] not in existing:
            bid, record = result
            new_records[bid] = record

    if new_records:
        data = load_members()
        data["members"].update(new_records)
        save_members(data)
        print(f"\nAdded {len(new_records)} new member records.")
        print(f"Total member cache size: {len(data['members'])} entries.")
    else:
        print("\nNo new members to add — cache is already up to date.")

    await client._http.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed the member cache from Congress.gov.")
    parser.add_argument(
        "--congress",
        type=int,
        default=None,
        metavar="N",
        help="Congress number to seed (default: all congresses)",
    )
    args = parser.parse_args()
    asyncio.run(main(args.congress))
