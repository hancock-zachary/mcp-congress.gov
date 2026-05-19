import asyncio
import json
from typing import Any

from .members import _fetch_member, _fetch_member_sponsored_legislation, _fetch_member_cosponsored_legislation
from .bills import _fetch_bill, _fetch_bill_cosponsors
from .client import get_client
from . import cache
from .cache import bill_key


async def _search_bills_raw(congress: int, params: dict[str, Any]) -> dict[str, Any]:
    return await get_client().get(f"bill/{congress}", params)


def _bills_for_member(bioguide_id: str, bill_data: dict) -> list[dict]:
    """Return all cached bill records where the member is sponsor or cosponsor."""
    return [
        r for r in bill_data.get("bills", [])
        if r.get("sponsor_id") == bioguide_id
        or any(c.get("id") == bioguide_id for c in r.get("cosponsors", []))
    ]


def _policy_area_counts(bills: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for b in bills:
        area = b.get("policy_area", "")
        if area:
            counts[area] = counts.get(area, 0) + 1
    return counts


async def get_member_profile(bioguide_id: str, sponsored_limit: int = 20) -> str:
    """
    Build a comprehensive profile for a member of Congress.
    Combines bio, committee assignments, sponsorship history, and cosponsorship activity
    into a single response. Use this before analyzing a member's priorities or predicting votes.
    Bio fields (chamber, district) are served from the member cache when available.
    """
    member_data, sponsored_data, cosponsored_data = await asyncio.gather(
        _fetch_member(bioguide_id),
        _fetch_member_sponsored_legislation(bioguide_id, limit=sponsored_limit),
        _fetch_member_cosponsored_legislation(bioguide_id, limit=sponsored_limit),
    )

    member = member_data.get("member", {})

    # Overlay cached chamber/district — the live member endpoint often omits these
    cached_member = cache.load_members().get("members", {}).get(bioguide_id, {})
    for field in ("chamber", "district"):
        if cached_member.get(field) is not None and not member.get(field):
            member[field] = cached_member[field]

    sponsored = sponsored_data.get("sponsoredLegislation", [])
    cosponsored = cosponsored_data.get("cosponsoredLegislation", [])

    policy_counts: dict[str, int] = {}
    for bill in sponsored + cosponsored:
        area = bill.get("policyArea", {})
        name = area.get("name", "Unknown") if isinstance(area, dict) else str(area or "Unknown")
        policy_counts[name] = policy_counts.get(name, 0) + 1

    top_areas = sorted(policy_counts.items(), key=lambda x: x[1], reverse=True)[:5]

    return json.dumps({
        "bioguide_id": bioguide_id,
        "member": member,
        "sponsored_legislation": sponsored,
        "cosponsored_legislation": cosponsored,
        "top_policy_areas": [{"area": a, "bill_count": c} for a, c in top_areas],
    })


async def get_member_stance(bioguide_id: str, topic: str) -> str:
    """
    Synthesize a member's position on a policy topic from their legislative activity.
    Searches sponsored and cosponsored bills for relevance to the topic keyword.
    Checks the bill cache first; falls back to live API if the member has no cached bills.
    """
    topic_lower = topic.lower()
    bill_data = cache.load()
    member_bills = _bills_for_member(bioguide_id, bill_data)

    if member_bills:
        sponsored_relevant = [
            b for b in member_bills
            if b.get("sponsor_id") == bioguide_id
            and topic_lower in (b.get("policy_area") or "").lower()
        ]
        cosponsored_relevant = [
            b for b in member_bills
            if any(c.get("id") == bioguide_id for c in b.get("cosponsors", []))
            and topic_lower in (b.get("policy_area") or "").lower()
        ]
        return json.dumps({
            "bioguide_id": bioguide_id,
            "topic": topic,
            "sponsored_relevant": sponsored_relevant,
            "cosponsored_relevant": cosponsored_relevant,
            "activity_count": len(sponsored_relevant) + len(cosponsored_relevant),
            "source": "cache",
            "note": "Results from bill cache, filtered by policy area keyword. Bill titles not available in cache.",
        })

    # Fall back to live API
    sponsored_data, cosponsored_data = await asyncio.gather(
        _fetch_member_sponsored_legislation(bioguide_id, limit=50),
        _fetch_member_cosponsored_legislation(bioguide_id, limit=50),
    )

    def is_relevant(bill: dict[str, Any]) -> bool:
        title = bill.get("title", "").lower()
        area = str(bill.get("policyArea", "")).lower()
        return topic_lower in title or topic_lower in area

    sponsored_relevant = [b for b in sponsored_data.get("sponsoredLegislation", []) if is_relevant(b)]
    cosponsored_relevant = [b for b in cosponsored_data.get("cosponsoredLegislation", []) if is_relevant(b)]

    return json.dumps({
        "bioguide_id": bioguide_id,
        "topic": topic,
        "sponsored_relevant": sponsored_relevant,
        "cosponsored_relevant": cosponsored_relevant,
        "activity_count": len(sponsored_relevant) + len(cosponsored_relevant),
        "source": "live",
        "note": "Results filtered by topic keyword match in bill title or policy area.",
    })


async def compare_member_alignment(bioguide_id_a: str, bioguide_id_b: str) -> str:
    """
    Compare the legislative alignment of two members of Congress.
    Returns shared policy areas, overlap in cosponsored bills, and party/chamber context.
    Useful for coalition building and identifying potential allies or opponents.
    Checks the bill cache first; falls back to live API for members without cached bills.
    """
    bill_data = cache.load()
    bills_a = _bills_for_member(bioguide_id_a, bill_data)
    bills_b = _bills_for_member(bioguide_id_b, bill_data)

    if bills_a and bills_b:
        members = cache.load_members().get("members", {})

        def member_info(bid: str) -> dict:
            m = members.get(bid, {})
            return {"bioguideId": bid, "name": m.get("name", ""), "party": m.get("party", ""),
                    "state": m.get("state", ""), "chamber": m.get("chamber", ""),
                    "district": m.get("district")}

        areas_a = {b["policy_area"] for b in bills_a if b.get("policy_area")}
        areas_b = {b["policy_area"] for b in bills_b if b.get("policy_area")}

        return json.dumps({
            "member_a": member_info(bioguide_id_a),
            "member_b": member_info(bioguide_id_b),
            "shared_policy_areas": sorted(areas_a & areas_b),
            "unique_to_a": sorted(areas_a - areas_b),
            "unique_to_b": sorted(areas_b - areas_a),
            "source": "cache",
        })

    # Fall back to live API for any member without cached bills
    fetch_a = (
        asyncio.gather(
            _fetch_member(bioguide_id_a),
            _fetch_member_sponsored_legislation(bioguide_id_a, limit=50),
            _fetch_member_cosponsored_legislation(bioguide_id_a, limit=50),
        ) if not bills_a else asyncio.gather(
            _fetch_member(bioguide_id_a),
        )
    )
    fetch_b = (
        asyncio.gather(
            _fetch_member(bioguide_id_b),
            _fetch_member_sponsored_legislation(bioguide_id_b, limit=50),
            _fetch_member_cosponsored_legislation(bioguide_id_b, limit=50),
        ) if not bills_b else asyncio.gather(
            _fetch_member(bioguide_id_b),
        )
    )

    results_a, results_b = await asyncio.gather(fetch_a, fetch_b)

    member_a_data = results_a[0]
    member_b_data = results_b[0]

    def areas_from_live(results: list, bills_cache: list[dict]) -> set[str]:
        if bills_cache:
            return {b["policy_area"] for b in bills_cache if b.get("policy_area")}
        sponsored = results[1] if len(results) > 1 else {}
        cosponsored = results[2] if len(results) > 2 else {}
        areas: set[str] = set()
        for bill in sponsored.get("sponsoredLegislation", []) + cosponsored.get("cosponsoredLegislation", []):
            area = bill.get("policyArea", {})
            if isinstance(area, dict):
                areas.add(area.get("name", ""))
            elif area:
                areas.add(str(area))
        return areas - {""}

    areas_a = areas_from_live(results_a, bills_a)
    areas_b = areas_from_live(results_b, bills_b)

    return json.dumps({
        "member_a": member_a_data.get("member", {}),
        "member_b": member_b_data.get("member", {}),
        "shared_policy_areas": sorted(areas_a & areas_b),
        "unique_to_a": sorted(areas_a - areas_b),
        "unique_to_b": sorted(areas_b - areas_a),
        "source": "mixed" if (bills_a or bills_b) else "live",
    })


ACTION_WEIGHTS = {
    "became public law": 6,
    "signed by president": 6,
    "passed senate": 5,
    "passed house": 5,
    "received in the senate": 4,
    "received in the house": 4,
    "placed on senate legislative calendar": 3,
    "reported by committee": 3,
    "ordered to be reported": 3,
    "passed committee": 3,
    "referred to": 1,
    "introduced": 1,
}


def _advancement_weight(latest_action_text: str) -> int:
    text = latest_action_text.lower()
    for keyword, weight in ACTION_WEIGHTS.items():
        if keyword in text:
            return weight
    return 1


async def analyze_bill_support(congress: int, bill_type: str, bill_number: str) -> str:
    """
    Analyze support for a specific bill.
    Returns the bill details, all current cosponsors, party breakdown, and state distribution.
    Uses the persistent cosponsor cache when available; falls back to a live API call otherwise.
    """
    k = bill_key(congress, bill_type, bill_number)
    cosponsor_index = cache.build_cosponsor_index(cache.load())

    if k in cosponsor_index and cosponsor_index[k].get("cosponsors") is not None:
        bill_data = await _fetch_bill(congress, bill_type, bill_number)
        members = cache.load_members().get("members", {})
        cached = cosponsor_index[k]
        cosponsors = [
            {
                "bioguideId": c["id"],
                "fullName": members.get(c["id"], {}).get("name", ""),
                "party": members.get(c["id"], {}).get("party", "Unknown"),
                "state": members.get(c["id"], {}).get("state", "Unknown"),
                "sponsorshipDate": c.get("date", ""),
            }
            for c in cached.get("cosponsors", [])
        ]
    else:
        bill_data, cosponsor_data = await asyncio.gather(
            _fetch_bill(congress, bill_type, bill_number),
            _fetch_bill_cosponsors(congress, bill_type, bill_number),
        )
        cosponsors = cosponsor_data.get("cosponsors", [])
    party_breakdown: dict[str, int] = {}
    state_breakdown: dict[str, int] = {}
    for cp in cosponsors:
        party = cp.get("party", "Unknown")
        state = cp.get("state", "Unknown")
        party_breakdown[party] = party_breakdown.get(party, 0) + 1
        state_breakdown[state] = state_breakdown.get(state, 0) + 1

    return json.dumps({
        "bill": bill_data.get("bill", {}),
        "cosponsors": cosponsors,
        "cosponsor_count": len(cosponsors),
        "party_breakdown": party_breakdown,
        "state_breakdown": state_breakdown,
    })


async def suggest_cosponsor_opportunities(
    bioguide_id: str, congress: int = 119, limit: int = 10
) -> str:
    """
    Suggest bills a member would be a strong fit to cosponsor.
    Finds active bills in the member's top policy areas that they have not yet cosponsored.
    Returns ranked suggestions with the matching policy area as reasoning.
    Checks the bill cache first; falls back to live API if the member has no cached bills.
    """
    bill_data = cache.load()
    member_bills = _bills_for_member(bioguide_id, bill_data)

    if member_bills:
        already_involved = {
            f"{b['congress']}{b['bill']}" for b in member_bills
        }
        top_areas = sorted(
            _policy_area_counts(member_bills).items(), key=lambda x: x[1], reverse=True
        )[:3]
        top_area_names = {a for a, _ in top_areas}

        candidate_bills: list[dict[str, Any]] = [
            {**b, "_matched_area": b.get("policy_area", "")}
            for b in bill_data.get("bills", [])
            if f"{b.get('congress')}{b.get('bill')}" not in already_involved
            and b.get("policy_area") in top_area_names
            and b.get("congress") == congress
        ]
        candidate_bills.sort(
            key=lambda b: _advancement_weight(""),
            reverse=True,
        )

        return json.dumps({
            "bioguide_id": bioguide_id,
            "congress": congress,
            "member_top_areas": [a for a, _ in top_areas],
            "suggestions": candidate_bills[:limit],
            "source": "cache",
        })

    # Fall back to live API
    sponsored_data, cosponsored_data = await asyncio.gather(
        _fetch_member_sponsored_legislation(bioguide_id, limit=50),
        _fetch_member_cosponsored_legislation(bioguide_id, limit=50),
    )

    sponsored = sponsored_data.get("sponsoredLegislation", [])
    cosponsored = cosponsored_data.get("cosponsoredLegislation", [])

    already_involved = {
        bill_key(b.get("congress", ""), b.get("type", ""), b.get("number", ""))
        for b in sponsored + cosponsored
    }

    policy_counts: dict[str, int] = {}
    for bill in sponsored + cosponsored:
        area = bill.get("policyArea", {})
        name = area.get("name", "") if isinstance(area, dict) else str(area)
        if name:
            policy_counts[name] = policy_counts.get(name, 0) + 1

    top_areas = sorted(policy_counts.items(), key=lambda x: x[1], reverse=True)[:3]

    candidate_bills = []
    for area_name, _ in top_areas:
        result = await _search_bills_raw(congress, {
            "query": area_name,
            "limit": 20,
            "offset": 0,
        })
        for bill in result.get("bills", []):
            key = bill_key(bill.get("congress", congress), bill.get("type", ""), bill.get("number", ""))
            if key not in already_involved:
                candidate_bills.append({**bill, "_matched_area": area_name})

    candidate_bills.sort(
        key=lambda b: _advancement_weight(b.get("latestAction", {}).get("text", "")),
        reverse=True,
    )

    return json.dumps({
        "bioguide_id": bioguide_id,
        "congress": congress,
        "member_top_areas": [a for a, _ in top_areas],
        "suggestions": candidate_bills[:limit],
        "source": "live",
    })


async def analyze_congress_priorities(congress: int = 119) -> str:
    """
    Identify the legislative priorities of a congress by analyzing bill advancement.
    Bills are grouped by policy area and weighted by how far they advanced
    (enacted > floor vote > committee passage > introduced).
    Fetches all bills via concurrent pagination, resolves policy areas from a
    persistent local cache (refreshed daily), and falls back to live API detail
    calls for any bills still missing a classification.
    Returns a ranked list of policy areas reflecting real legislative momentum.
    """
    client = get_client()

    # Refresh the persistent policy-area cache if it's more than 24 hours old
    if cache.is_stale():
        await cache.refresh(client, congresses=[congress])

    page_size = 250

    # Fetch first page to get total count
    first_page = await _search_bills_raw(congress, {"limit": page_size, "offset": 0, "sort": "updateDate+desc"})
    if "error" in first_page:
        return json.dumps(first_page)

    total_available = first_page.get("pagination", {}).get("count", 0)
    all_bills: list[dict[str, Any]] = list(first_page.get("bills", []))

    # Fetch all remaining pages concurrently
    if total_available > page_size:
        offsets = range(page_size, total_available, page_size)
        extra_pages = await asyncio.gather(*[
            _search_bills_raw(congress, {"limit": page_size, "offset": offset, "sort": "updateDate+desc"})
            for offset in offsets
        ])
        for page in extra_pages:
            all_bills.extend(page.get("bills", []))

    # Apply policy areas from persistent cache before falling back to API calls
    cached_index = cache.build_index(cache.load())
    for bill in all_bills:
        if not bill.get("policyArea"):
            k = bill_key(bill.get("congress", congress), bill.get("type", ""), bill.get("number", ""))
            if k in cached_index:
                bill["policyArea"] = {"name": cached_index[k]}

    # For bills still missing policyArea, enrich via detail calls.
    # Sort by advancement weight so the most impactful bills get classified first.
    bills_needing_area = [b for b in all_bills if not b.get("policyArea")]
    bills_needing_area.sort(
        key=lambda b: _advancement_weight(b.get("latestAction", {}).get("text", "")),
        reverse=True,
    )
    sample = bills_needing_area[:500]
    if sample:
        detail_results = await asyncio.gather(*[
            _fetch_bill(b["congress"], b["type"], b["number"])
            for b in sample
        ])
        new_entries: list[dict] = []
        new_index: dict[str, str] = {}
        for detail in detail_results:
            bd = detail.get("bill", {})
            c = bd.get("congress", congress)
            t = bd.get("type", "").lower()
            n = bd.get("number", "")
            area = bd.get("policyArea", {})
            if isinstance(area, dict) and area.get("name") and t and n:
                k = bill_key(c, t, n)
                new_entries.append({"congress": c, "bill": f"{t}{n}", "policy_area": area["name"]})
                new_index[k] = area["name"]

        if new_entries:
            cache.update_many(new_entries)

        for bill in all_bills:
            if not bill.get("policyArea"):
                k = bill_key(bill.get("congress", congress), bill.get("type", ""), bill.get("number", ""))
                if k in new_index:
                    bill["policyArea"] = {"name": new_index[k]}

    area_stats: dict[str, dict[str, Any]] = {}
    for bill in all_bills:
        area = bill.get("policyArea", {})
        area_name = area.get("name", "Uncategorized") if isinstance(area, dict) else str(area or "Uncategorized")

        if area_name not in area_stats:
            area_stats[area_name] = {
                "area": area_name,
                "total_bills": 0,
                "enacted_count": 0,
                "floor_vote_count": 0,
                "committee_passage_count": 0,
                "introduced_only_count": 0,
                "total_weight": 0,
            }

        stats = area_stats[area_name]
        stats["total_bills"] += 1
        action_text = bill.get("latestAction", {}).get("text", "")
        weight = _advancement_weight(action_text)
        stats["total_weight"] += weight

        action_lower = action_text.lower()
        if "became public law" in action_lower or "signed by president" in action_lower:
            stats["enacted_count"] += 1
        elif "passed house" in action_lower or "passed senate" in action_lower:
            stats["floor_vote_count"] += 1
        elif "reported by committee" in action_lower or "ordered to be reported" in action_lower:
            stats["committee_passage_count"] += 1
        else:
            stats["introduced_only_count"] += 1

    # Exclude the catch-all bucket from ranked results — surface it separately
    uncategorized = area_stats.pop("Uncategorized", None)
    ranked = sorted(area_stats.values(), key=lambda s: s["total_weight"], reverse=True)

    return json.dumps({
        "congress": congress,
        "bills_analyzed": len(all_bills),
        "total_available": total_available,
        "policy_areas": ranked,
        "uncategorized_bills": uncategorized["total_bills"] if uncategorized else 0,
        "note": "Areas ranked by total advancement weight. Enacted bills weighted 6x vs introduced-only (1x). Bills without CRS policy area classifications are excluded from ranking.",
    })
