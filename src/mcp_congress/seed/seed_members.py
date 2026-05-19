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
from mcp_congress.cache import load_members, save_members, update_members, _now_utc

PAGE_SIZE = 250
CONCURRENT_PAGES = 5


async def fetch_all_members(client: CongressClient, congress: int | None) -> list[dict]:
    endpoint = f"member/{congress}" if congress else "member"
    # currentMember=true limits the response to currently serving members only
    base_params: dict = {"limit": PAGE_SIZE, "offset": 0, "sort": "name", "currentMember": "true"}
    first = await client.get(endpoint, base_params)
    if "error" in first:
        print(f"  Error fetching members: {first}")
        return []

    total = first.get("pagination", {}).get("count", 0)
    members = list(first.get("members", []))
    print(f"  {total} current members — fetching {max(0, (total - 1) // PAGE_SIZE)} more pages...")

    if total > PAGE_SIZE:
        offsets = list(range(PAGE_SIZE, total, PAGE_SIZE))
        for i in range(0, len(offsets), CONCURRENT_PAGES):
            chunk = offsets[i:i + CONCURRENT_PAGES]
            pages = await asyncio.gather(*[
                client.get(endpoint, {**base_params, "offset": offset})
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


def _chamber_from(raw: dict) -> str:
    """Resolve chamber from the most recent term — the list endpoint doesn't
    expose a top-level chamber field."""
    # Some endpoints do include a top-level field
    top = (raw.get("chamber") or "").strip()
    if top:
        return _CHAMBER_MAP.get(top.lower(), top)

    terms = raw.get("terms", [])
    # The API sometimes wraps terms as {"item": [...]}
    if isinstance(terms, dict):
        terms = terms.get("item", [])
    if terms:
        last = terms[-1] if isinstance(terms, list) else terms
        raw_name = (last.get("chamber") or "").strip()
        return _CHAMBER_MAP.get(raw_name.lower(), raw_name)
    return ""


def _normalize(raw: dict) -> tuple[str, dict] | None:
    """Extract bioguide ID and normalized member record from a raw API member object."""
    bid = raw.get("bioguideId", "")
    if not bid:
        return None
    district = raw.get("district")
    return bid, {
        "name": raw.get("directOrderName") or raw.get("invertedOrderName") or raw.get("name", ""),
        "party": raw.get("partyName", ""),
        "state": raw.get("state", ""),
        "chamber": _chamber_from(raw),
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
        update_members(new_records)  # merges fields and stamps last_updated
        data = load_members()
        print(f"\nAdded {len(new_records)} new member records.")
        print(f"Total member cache size: {len(data['members'])} entries.")
    else:
        # Still stamp last_updated so the weekly staleness clock resets
        data = load_members()
        data["last_updated"] = _now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")
        save_members(data)
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
