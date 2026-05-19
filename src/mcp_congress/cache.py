import asyncio
import json
from datetime import datetime, timezone, timedelta
from importlib.resources import files
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .client import CongressClient

_CACHE_FILE = files("mcp_congress.data").joinpath("policy_areas.json")
_STALE_AFTER_HOURS = 24
_REFRESH_BATCH = 500


def bill_key(congress: int | str, bill_type: str, number: str) -> str:
    return f"{congress}{bill_type.lower()}{number}"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def load() -> dict[str, Any]:
    try:
        return json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"last_updated": "2025-01-01T00:00:00Z", "bills": []}


def save(data: dict[str, Any]) -> None:
    try:
        Path(str(_CACHE_FILE)).write_text(
            json.dumps(data, indent=2), encoding="utf-8"
        )
    except Exception:
        pass  # read-only install path — silently skip


def build_index(data: dict[str, Any]) -> dict[str, str]:
    """Return a fast lookup dict keyed by bill_key() from the stored bill list."""
    return {
        f"{r['congress']}{r['bill']}": r["policy_area"]
        for r in data.get("bills", [])
    }


def update_many(entries: list[dict[str, Any]]) -> None:
    """Append new {congress, bill, policy_area} records, skipping duplicates."""
    data = load()
    existing = {f"{r['congress']}{r['bill']}" for r in data["bills"]}
    for entry in entries:
        k = f"{entry['congress']}{entry['bill']}"
        if k not in existing:
            data["bills"].append(entry)
            existing.add(k)
    save(data)


def is_stale() -> bool:
    data = load()
    try:
        last = datetime.fromisoformat(data["last_updated"].replace("Z", "+00:00"))
        return (_now_utc() - last) > timedelta(hours=_STALE_AFTER_HOURS)
    except Exception:
        return True


async def refresh(client: "CongressClient", congresses: list[int]) -> int:
    """
    Fetch bills updated since last_updated across the given congresses,
    enrich with policy areas from detail calls, and persist to cache.
    Returns the number of new records added.
    """
    data = load()
    existing = build_index(data)
    try:
        from_dt = datetime.fromisoformat(
            data["last_updated"].replace("Z", "+00:00")
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        from_dt = "2025-01-01T00:00:00Z"

    # Collect bills updated since last refresh across all requested congresses
    updated_bills: list[dict[str, Any]] = []
    for congress in congresses:
        page_result = await client.get(
            f"bill/{congress}",
            {"fromDateTime": from_dt, "limit": 250, "sort": "updateDate+desc"},
        )
        if "error" in page_result:
            continue
        total = page_result.get("pagination", {}).get("count", 0)
        updated_bills.extend(page_result.get("bills", []))

        if total > 250:
            offsets = range(250, min(total, _REFRESH_BATCH), 250)
            extra = await asyncio.gather(*[
                client.get(f"bill/{congress}", {"fromDateTime": from_dt, "limit": 250, "offset": offset, "sort": "updateDate+desc"})
                for offset in offsets
            ])
            for page in extra:
                updated_bills.extend(page.get("bills", []))

    # Only enrich bills not already in cache
    to_enrich = [
        b for b in updated_bills
        if bill_key(b.get("congress", ""), b.get("type", ""), b.get("number", "")) not in existing
        and b.get("congress") and b.get("type") and b.get("number")
    ][:_REFRESH_BATCH]

    new_entries: list[dict[str, Any]] = []
    if to_enrich:
        from .bills import _fetch_bill
        details = await asyncio.gather(*[
            _fetch_bill(b["congress"], b["type"], b["number"])
            for b in to_enrich
        ])
        for detail in details:
            b = detail.get("bill", {})
            congress = b.get("congress", "")
            bill = f"{b.get('type', '').lower()}{b.get('number', '')}"
            area = b.get("policyArea", {})
            if isinstance(area, dict) and area.get("name") and congress and bill:
                new_entries.append({
                    "congress": congress,
                    "bill": bill,
                    "policy_area": area["name"],
                })

    # Reload so we merge with any changes made since we started
    fresh = load()
    existing_keys = {f"{r['congress']}{r['bill']}" for r in fresh["bills"]}
    for entry in new_entries:
        k = f"{entry['congress']}{entry['bill']}"
        if k not in existing_keys:
            fresh["bills"].append(entry)
            existing_keys.add(k)
    fresh["last_updated"] = _now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")
    save(fresh)

    return len(new_entries)
