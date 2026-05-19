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


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def load() -> dict[str, Any]:
    try:
        return json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"last_updated": "2025-01-01T00:00:00Z", "bills": {}}


def save(data: dict[str, Any]) -> None:
    try:
        Path(str(_CACHE_FILE)).write_text(
            json.dumps(data, indent=2), encoding="utf-8"
        )
    except Exception:
        pass  # read-only install path — silently skip


def get_policy_area(bill_key: str) -> str | None:
    return load()["bills"].get(bill_key)


def update_many(mappings: dict[str, str]) -> None:
    data = load()
    data["bills"].update(mappings)
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
    Returns the number of new bill→area mappings added.
    """
    data = load()
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
    existing = data["bills"]
    to_enrich = [
        b for b in updated_bills
        if f"{b.get('type', '')}{b.get('number', '')}" not in existing
        and b.get("congress") and b.get("type") and b.get("number")
    ][:_REFRESH_BATCH]

    new_mappings: dict[str, str] = {}
    if to_enrich:
        from .bills import _fetch_bill
        details = await asyncio.gather(*[
            _fetch_bill(b["congress"], b["type"], b["number"])
            for b in to_enrich
        ])
        for detail in details:
            bill = detail.get("bill", {})
            key = f"{bill.get('type', '')}{bill.get('number', '')}"
            area = bill.get("policyArea", {})
            if isinstance(area, dict) and area.get("name") and key:
                new_mappings[key] = area["name"]

    data["bills"].update(new_mappings)
    data["last_updated"] = _now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")
    save(data)

    return len(new_mappings)
