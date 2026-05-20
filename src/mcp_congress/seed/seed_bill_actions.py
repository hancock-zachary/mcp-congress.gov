"""
Seed the bill actions cache with legislative history for every bill in bill_cache.json.

Run this after seed_bills.py to populate
src/mcp_congress/data/bill_actions_cache.json.

Usage:
    uv run python src/mcp_congress/seed/seed_bill_actions.py
    uv run python src/mcp_congress/seed/seed_bill_actions.py --batch 20
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
from mcp_congress.bills import _fetch_bill_actions
from mcp_congress.cache import load, load_actions, update_actions, bill_key

DEFAULT_BATCH = 10
SAVE_EVERY = 200
BASE_PAUSE = 1.0
BACKOFF_PAUSE = 15.0


def _parse_bill_ref(record: dict) -> tuple[int, str, str] | None:
    """Extract (congress, type, number) from a bill cache record."""
    congress = record.get("congress")
    bill = record.get("bill", "")  # e.g. "hr1", "s42", "hjres8"
    if not congress or not bill:
        return None
    # Split type (letters) from number (digits)
    i = next((i for i, c in enumerate(bill) if c.isdigit()), None)
    if i is None or i == 0:
        return None
    return int(congress), bill[:i], bill[i:]


def _normalize_actions(raw_actions: list[dict]) -> list[dict]:
    return [
        {
            "date": a.get("actionDate", ""),
            "text": a.get("text", ""),
            "type": a.get("type", ""),
        }
        for a in raw_actions
        if a.get("actionDate") or a.get("text")
    ]


async def seed_actions(client: CongressClient, batch_size: int) -> None:
    bill_data = load()
    actions_data = load_actions()
    existing_keys = set(actions_data["actions"].keys())

    to_fetch = [
        ref for r in bill_data.get("bills", [])
        if (ref := _parse_bill_ref(r)) is not None
        and bill_key(ref[0], ref[1], ref[2]) not in existing_keys
    ]

    total = len(to_fetch)
    print(f"Bills needing action history: {total}")
    if not total:
        print("Actions cache is already up to date.")
        return

    fetched = 0
    timeouts = 0
    unsaved: dict = {}
    pause = BASE_PAUSE

    for i in range(0, total, batch_size):
        chunk = to_fetch[i:i + batch_size]
        results = await asyncio.gather(*[
            _fetch_bill_actions(congress, bill_type, number)
            for congress, bill_type, number in chunk
        ], return_exceptions=True)

        batch_timeouts = 0
        for (congress, bill_type, number), result in zip(chunk, results):
            k = bill_key(congress, bill_type, number)
            if isinstance(result, Exception) or (isinstance(result, dict) and "error" in result):
                timeouts += 1
                batch_timeouts += 1
                continue
            raw = result.get("actions", [])
            items = raw if isinstance(raw, list) else raw.get("items", [])
            unsaved[k] = _normalize_actions(items)
            fetched += 1

        if len(unsaved) >= SAVE_EVERY:
            update_actions(unsaved)
            unsaved.clear()

        done = min(i + batch_size, total)
        parts = [f"{fetched} fetched"]
        if timeouts:
            parts.append(f"{timeouts} timeouts")
        print(f"  Processed {done}/{total} bills ({', '.join(parts)})")

        if batch_timeouts == len(chunk):
            pause = BACKOFF_PAUSE
            print(f"  Rate limit detected — pausing {int(pause)}s")
        elif batch_timeouts == 0:
            pause = BASE_PAUSE

        await asyncio.sleep(pause)

    if unsaved:
        update_actions(unsaved)

    print(f"\nDone. {fetched} bills with actions cached, {timeouts} timeouts.")


async def main(batch_size: int) -> None:
    api_key = os.environ.get("CONGRESS_API_KEY")
    if not api_key:
        print("Error: CONGRESS_API_KEY environment variable is not set.")
        sys.exit(1)

    client = CongressClient(api_key=api_key, timeout=60.0)
    existing = load_actions()
    print(f"Existing action cache entries: {len(existing['actions'])}")
    await seed_actions(client, batch_size)
    await client._http.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed bill action history from Congress.gov.")
    parser.add_argument(
        "--batch",
        type=int,
        default=DEFAULT_BATCH,
        metavar="N",
        help=f"Concurrent action requests per batch (default: {DEFAULT_BATCH})",
    )
    args = parser.parse_args()
    asyncio.run(main(args.batch))
