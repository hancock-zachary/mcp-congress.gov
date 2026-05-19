import asyncio
import json
from datetime import datetime, timezone, timedelta
from importlib.resources import files
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .client import CongressClient

_CACHE_FILE = files("mcp_congress.data").joinpath("bill_cache.json")
_MEMBER_CACHE_FILE = files("mcp_congress.data").joinpath("member_cache.json")
_STALE_AFTER_HOURS = 24
_MEMBER_STALE_AFTER_HOURS = 168  # 7 days
_REFRESH_BATCH = 500


def bill_key(congress: int | str, bill_type: str, number: str) -> str:
    return f"{congress}{bill_type.lower()}{number}"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# --- Bill cache ---

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
    """Return {bill_key: policy_area} for O(1) policy-area lookups."""
    return {
        f"{r['congress']}{r['bill']}": r["policy_area"]
        for r in data.get("bills", [])
        if r.get("policy_area")
    }


def build_cosponsor_index(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return {bill_key: {sponsor_id, cosponsors: [{id, date}]}} for O(1) lookups."""
    return {
        f"{r['congress']}{r['bill']}": {
            "sponsor_id": r.get("sponsor_id"),
            "cosponsors": r.get("cosponsors", []),
        }
        for r in data.get("bills", [])
        if r.get("sponsor_id") is not None or r.get("cosponsors") is not None
    }


def update_many(entries: list[dict[str, Any]]) -> None:
    """Upsert bill records. New entries are appended; existing ones are merged."""
    data = load()
    index = {f"{r['congress']}{r['bill']}": i for i, r in enumerate(data["bills"])}
    for entry in entries:
        k = f"{entry['congress']}{entry['bill']}"
        if k in index:
            data["bills"][index[k]].update(entry)
        else:
            data["bills"].append(entry)
            index[k] = len(data["bills"]) - 1
    save(data)


# --- Member cache ---

def load_members() -> dict[str, Any]:
    try:
        return json.loads(_MEMBER_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"last_updated": "2025-01-01T00:00:00Z", "members": {}}


def save_members(data: dict[str, Any]) -> None:
    try:
        Path(str(_MEMBER_CACHE_FILE)).write_text(
            json.dumps(data, indent=2), encoding="utf-8"
        )
    except Exception:
        pass


def update_members(members: dict[str, Any]) -> None:
    """Upsert {bioguide_id: {name, party, state}} records and stamp last_updated."""
    data = load_members()
    data["members"].update(members)
    data["last_updated"] = _now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")
    save_members(data)


def is_members_stale() -> bool:
    data = load_members()
    try:
        last = datetime.fromisoformat(data["last_updated"].replace("Z", "+00:00"))
        return (_now_utc() - last) > timedelta(hours=_MEMBER_STALE_AFTER_HOURS)
    except Exception:
        return True


# --- Shared builder ---

def _build_entry(
    detail: dict[str, Any], cosp_data: dict[str, Any] | None = None
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """
    Build a normalised bill cache record and a dict of member records to upsert.

    Returns (bill_entry | None, {bioguide_id: {name, party, state}}).
    Bill entry stores only sponsor_id and cosponsor [{id, date}] — full member
    details go into the member cache to avoid repetition across bills.
    """
    b = detail.get("bill", {})
    congress = b.get("congress", "")
    t = b.get("type", "").lower()
    n = b.get("number", "")
    if not (congress and t and n):
        return None, {}

    entry: dict[str, Any] = {"congress": congress, "bill": f"{t}{n}"}
    members: dict[str, Any] = {}

    area = b.get("policyArea", {})
    if isinstance(area, dict) and area.get("name"):
        entry["policy_area"] = area["name"]

    raw_sponsor = b.get("sponsor", {})
    if isinstance(raw_sponsor, dict) and raw_sponsor.get("bioguideId"):
        sid = raw_sponsor["bioguideId"]
        entry["sponsor_id"] = sid
        members[sid] = {
            "name": raw_sponsor.get("fullName", ""),
            "party": raw_sponsor.get("party", ""),
            "state": raw_sponsor.get("state", ""),
        }

    if cosp_data is not None:
        entry["cosponsors"] = []
        for c in cosp_data.get("cosponsors", []):
            cid = c.get("bioguideId", "")
            if cid:
                entry["cosponsors"].append({"id": cid, "date": c.get("sponsorshipDate", "")})
                members[cid] = {
                    "name": c.get("fullName", ""),
                    "party": c.get("party", ""),
                    "state": c.get("state", ""),
                }

    return (entry if len(entry) > 2 else None), members


# --- Staleness / refresh ---

def is_stale() -> bool:
    data = load()
    try:
        last = datetime.fromisoformat(data["last_updated"].replace("Z", "+00:00"))
        return (_now_utc() - last) > timedelta(hours=_STALE_AFTER_HOURS)
    except Exception:
        return True


async def refresh(client: "CongressClient", congresses: list[int]) -> int:
    """
    Fetch bills with recent legislative action across the given congresses,
    enrich with policy area, sponsor, and cosponsor data, and persist to cache.
    Returns the number of new records added.

    Filters by latestAction.actionDate >= last_updated date. Pages are fetched
    in updateDate+desc order and pagination stops early once bills fall below
    the last_updated threshold — avoiding needless API calls for stale bills.
    """
    data = load()
    existing = build_index(data)
    try:
        last_dt = datetime.fromisoformat(data["last_updated"].replace("Z", "+00:00"))
        last_date = last_dt.date()
    except Exception:
        last_date = datetime(2025, 1, 1, tzinfo=timezone.utc).date()

    # Collect candidates: bills whose latest legislative action is on or after last_date
    candidates: list[dict[str, Any]] = []
    for congress in congresses:
        offset = 0
        while True:
            page_result = await client.get(
                f"bill/{congress}",
                {"limit": 250, "offset": offset, "sort": "updateDate+desc"},
            )
            if "error" in page_result:
                break

            bills = page_result.get("bills", [])
            if not bills:
                break

            stop_after_page = False
            for bill in bills:
                update_date_str = bill.get("updateDate", "")
                try:
                    update_dt = datetime.fromisoformat(update_date_str.replace("Z", "+00:00"))
                    if update_dt < last_dt:
                        stop_after_page = True
                        break
                except Exception:
                    pass

                action_date_str = bill.get("latestAction", {}).get("actionDate", "")
                try:
                    action_date = datetime.strptime(action_date_str, "%Y-%m-%d").date()
                    if action_date >= last_date:
                        candidates.append(bill)
                except Exception:
                    pass

            if stop_after_page or len(candidates) >= _REFRESH_BATCH:
                break

            total = page_result.get("pagination", {}).get("count", 0)
            offset += 250
            if offset >= total:
                break

    # Only enrich bills not already in cache
    to_enrich = [
        b for b in candidates
        if bill_key(b.get("congress", ""), b.get("type", ""), b.get("number", "")) not in existing
        and b.get("congress") and b.get("type") and b.get("number")
    ][:_REFRESH_BATCH]

    new_entries: list[dict[str, Any]] = []
    all_members: dict[str, Any] = {}
    if to_enrich:
        from .bills import _fetch_bill, _fetch_bill_cosponsors
        pairs = await asyncio.gather(*[
            asyncio.gather(
                _fetch_bill(b["congress"], b["type"], b["number"]),
                _fetch_bill_cosponsors(b["congress"], b["type"], b["number"]),
            )
            for b in to_enrich
        ])
        for detail, cosp_data in pairs:
            entry, members = _build_entry(detail, cosp_data)
            if entry:
                new_entries.append(entry)
                all_members.update(members)

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

    if all_members and is_members_stale():
        update_members(all_members)

    return len(new_entries)
