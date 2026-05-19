"""
Seed the policy-area cache with a full population of bill→policyArea mappings.

Run this once (or whenever you want a fresh full seed) to pre-populate
src/mcp_congress/data/policy_areas.json before committing to the repo.
Teammates who pull the repo get the benefit of these lookups without needing
to make any API calls themselves.

Usage:
    uv run python src/mcp_congress/seed/seed_policy_areas.py
    uv run python src/mcp_congress/seed/seed_policy_areas.py --congresses 118 119
    uv run python src/mcp_congress/seed/seed_policy_areas.py --congresses 119 --batch 250
"""

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow running from any working directory
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv
load_dotenv()

from mcp_congress.client import CongressClient
from mcp_congress.bills import _fetch_bill
from mcp_congress import cache
from mcp_congress.cache import bill_key

PAGE_SIZE = 250
CONCURRENT_PAGES = 5   # pages fetched in parallel at a time
DEFAULT_BATCH = 20     # detail calls fired in parallel at a time


async def fetch_all_bills(client: CongressClient, congress: int) -> list[dict]:
    first = await client.get(f"bill/{congress}", {"limit": PAGE_SIZE, "offset": 0, "sort": "updateDate+desc"})
    if "error" in first:
        print(f"  Error fetching bills for congress {congress}: {first}")
        return []

    total = first.get("pagination", {}).get("count", 0)
    bills = list(first.get("bills", []))
    print(f"  Congress {congress}: {total} total bills — fetching {(total // PAGE_SIZE)} more pages...")

    if total > PAGE_SIZE:
        offsets = list(range(PAGE_SIZE, total, PAGE_SIZE))
        for i in range(0, len(offsets), CONCURRENT_PAGES):
            chunk = offsets[i:i + CONCURRENT_PAGES]
            pages = await asyncio.gather(*[
                client.get(f"bill/{congress}", {"limit": PAGE_SIZE, "offset": offset, "sort": "updateDate+desc"})
                for offset in chunk
            ])
            for page in pages:
                bills.extend(page.get("bills", []))
            print(f"  Fetched {min(len(bills), total)}/{total} bills")

    return bills


async def enrich_batch(bills: list[dict], client: CongressClient, batch_size: int) -> dict[str, str]:
    mappings: dict[str, str] = {}
    total = len(bills)
    errors = 0

    for i in range(0, total, batch_size):
        chunk = bills[i:i + batch_size]
        results = await asyncio.gather(*[
            _fetch_bill(b["congress"], b["type"], b["number"])
            for b in chunk
        ], return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                errors += 1
                continue
            b = result.get("bill", {})
            k = bill_key(b.get("congress", ""), b.get("type", ""), b.get("number", ""))
            area = b.get("policyArea", {})
            if isinstance(area, dict) and area.get("name") and k:
                mappings[k] = area["name"]

        done = min(i + batch_size, total)
        error_note = f", {errors} timeouts skipped" if errors else ""
        print(f"  Enriched {done}/{total} bills ({len(mappings)} mapped{error_note})")

    return mappings


async def main(congresses: list[int], batch_size: int) -> None:
    api_key = os.environ.get("CONGRESS_API_KEY")
    if not api_key:
        print("Error: CONGRESS_API_KEY environment variable is not set.")
        print("Add it to your .env file or export it before running this script.")
        sys.exit(1)

    client = CongressClient(api_key=api_key, timeout=60.0)
    data = cache.load()
    existing = data["bills"]
    print(f"Existing cache entries: {len(existing)}")

    all_new: dict[str, str] = {}

    for congress in congresses:
        print(f"\nFetching bills for the {congress}th Congress...")
        bills = await fetch_all_bills(client, congress)

        to_enrich = [
            b for b in bills
            if bill_key(b.get("congress", ""), b.get("type", ""), b.get("number", "")) not in existing
            and b.get("congress") and b.get("type") and b.get("number")
        ]
        print(f"  {len(to_enrich)} bills need enrichment (not yet in cache)")

        if to_enrich:
            new = await enrich_batch(to_enrich, client, batch_size)
            all_new.update(new)

    if all_new:
        data["bills"].update(all_new)
        data["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        cache.save(data)
        print(f"\nSaved {len(all_new)} new policy-area mappings to cache.")
        print(f"Total cache size: {len(data['bills'])} entries.")
    else:
        print("\nNo new mappings to add — cache is already up to date.")

    await client._http.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed the policy-area cache from Congress.gov.")
    parser.add_argument(
        "--congresses",
        nargs="+",
        type=int,
        default=[119],
        metavar="N",
        help="Congress numbers to seed (default: 119)",
    )
    parser.add_argument(
        "--batch",
        type=int,
        default=DEFAULT_BATCH,
        metavar="N",
        help=f"Number of detail calls to fire concurrently (default: {DEFAULT_BATCH})",
    )
    args = parser.parse_args()
    asyncio.run(main(args.congresses, args.batch))
