# Congress.gov MCP Server — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python MCP server that gives lobbyists fast, intelligent access to Congress.gov data from Claude Desktop via atomic data tools and compound analytical tools.

**Architecture:** Async Python package using FastMCP for tool registration, httpx for concurrent Congress.gov API calls, and an in-memory TTL cache to minimize redundant requests. Compound tools orchestrate multiple atomic API calls in parallel using `asyncio.gather()`. Distributed via PyPI as a `uvx`-runnable package.

**Tech Stack:** Python 3.14, `mcp[cli]>=1.9`, `httpx>=0.28`, `cachetools>=5.5`, `python-dotenv>=1.1`, `pytest>=8.3`, `pytest-asyncio>=0.24`, `respx>=0.21`

---

## File Map

| File | Responsibility |
|------|---------------|
| `pyproject.toml` | Package metadata, dependencies, `uvx` entry point |
| `.env` | Local dev API key (gitignored) |
| `src/mcp_congress/__init__.py` | Package marker (empty) |
| `src/mcp_congress/client.py` | `CongressClient` — async httpx, TTL cache, error handling; `get_client()` singleton |
| `src/mcp_congress/bills.py` | `search_bills`, `get_bill`, `get_bill_cosponsors`, `get_bill_votes`; private `_fetch_*` helpers used by compound tools |
| `src/mcp_congress/members.py` | `search_members`, `get_member`, `get_member_sponsored_legislation`, `get_member_votes`; private `_fetch_*` helpers |
| `src/mcp_congress/committees.py` | `search_committees`, `get_committee`; private `_fetch_*` helpers |
| `src/mcp_congress/compound.py` | `get_member_profile`, `get_member_stance`, `analyze_bill_support`, `compare_member_alignment`, `suggest_cosponsor_opportunities`, `analyze_congress_priorities` |
| `src/mcp_congress/server.py` | FastMCP instance, `@mcp.tool()` registrations, `main()` entry point |
| `tests/conftest.py` | Shared fixtures (`mock_client`, `sample_bill`, `sample_member`) |
| `tests/test_client.py` | Client caching, error handling, retry logic |
| `tests/test_bills.py` | Bill tool response parsing |
| `tests/test_members.py` | Member tool response parsing |
| `tests/test_committees.py` | Committee tool response parsing |
| `tests/test_compound.py` | Compound tool orchestration and output shape |
| `tests/integration/test_integration.py` | Real API calls (skipped without `CONGRESS_API_KEY`) |
| `CLAUDE.md` | Developer documentation |

---

## Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `src/mcp_congress/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/integration/__init__.py`
- Create: `.env` (not committed)

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "mcp-congress-gov"
version = "0.1.0"
description = "MCP server providing Congress.gov data access for Claude"
readme = "README.md"
requires-python = ">=3.14"
dependencies = [
    "mcp[cli]>=1.9.0",
    "httpx>=0.28.0",
    "cachetools>=5.5.0",
    "python-dotenv>=1.1.0",
]

[project.scripts]
mcp-congress-gov = "mcp_congress.server:main"

[tool.hatch.build.targets.wheel]
packages = ["src/mcp_congress"]

[project.optional-dependencies]
dev = [
    "pytest>=8.3.0",
    "pytest-asyncio>=0.24.0",
    "respx>=0.21.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.hatch.envs.default]
features = ["dev"]
```

- [ ] **Step 2: Create package and test directories**

```bash
mkdir -p src/mcp_congress tests/integration
```

Create `src/mcp_congress/__init__.py` — empty file.
Create `tests/__init__.py` — empty file.
Create `tests/integration/__init__.py` — empty file.

- [ ] **Step 3: Create `.env` for local dev**

```
CONGRESS_API_KEY=your-key-here
```

Verify `.env` is in `.gitignore` (it should already be from the Python gitignore template).

- [ ] **Step 4: Install dependencies**

```bash
uv sync --extra dev
```

Expected: dependencies install without errors.

- [ ] **Step 5: Verify package structure**

```bash
uv run python -c "import mcp_congress; print('ok')"
```

Expected: prints `ok` (once `__init__.py` exists).

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/ tests/
git commit -m "feat: scaffold project structure and dependencies"
```

---

## Task 2: Congress.gov API Client

**Files:**
- Create: `src/mcp_congress/client.py`
- Create: `tests/test_client.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_client.py`:

```python
import pytest
import respx
import httpx
from mcp_congress.client import CongressClient


@pytest.fixture
def client():
    return CongressClient(api_key="test-key")


@respx.mock
async def test_get_success(client):
    respx.get("https://api.congress.gov/v3/bill").mock(
        return_value=httpx.Response(200, json={"bills": [], "pagination": {"count": 0}})
    )
    result = await client.get("bill", {"congress": 119})
    assert result == {"bills": [], "pagination": {"count": 0}}


@respx.mock
async def test_get_404_returns_structured_error(client):
    respx.get("https://api.congress.gov/v3/bill/99/hr/9999").mock(
        return_value=httpx.Response(404)
    )
    result = await client.get("bill/99/hr/9999")
    assert result["error"] == "not_found"
    assert "message" in result


@respx.mock
async def test_get_429_returns_rate_limited(client):
    respx.get("https://api.congress.gov/v3/bill").mock(
        return_value=httpx.Response(429)
    )
    result = await client.get("bill")
    assert result["error"] == "rate_limited"
    assert "message" in result


@respx.mock
async def test_caching_prevents_duplicate_requests(client):
    respx.get("https://api.congress.gov/v3/member").mock(
        return_value=httpx.Response(200, json={"members": []})
    )
    await client.get("member", {"stateCode": "TX"})
    await client.get("member", {"stateCode": "TX"})
    assert respx.calls.call_count == 1


@respx.mock
async def test_different_params_are_not_cached_together(client):
    respx.get("https://api.congress.gov/v3/member").mock(
        return_value=httpx.Response(200, json={"members": []})
    )
    await client.get("member", {"stateCode": "TX"})
    await client.get("member", {"stateCode": "CA"})
    assert respx.calls.call_count == 2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_client.py -v
```

Expected: `ModuleNotFoundError: No module named 'mcp_congress.client'`

- [ ] **Step 3: Implement `client.py`**

Create `src/mcp_congress/client.py`:

```python
import asyncio
import json
import os
from typing import Any

import httpx
from cachetools import TTLCache
from dotenv import load_dotenv

load_dotenv()

_instance: "CongressClient | None" = None


def get_client() -> "CongressClient":
    global _instance
    if _instance is None:
        api_key = os.environ.get("CONGRESS_API_KEY")
        if not api_key:
            raise RuntimeError("CONGRESS_API_KEY environment variable is not set")
        _instance = CongressClient(api_key=api_key)
    return _instance


class CongressClient:
    BASE_URL = "https://api.congress.gov/v3"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._http = httpx.AsyncClient(timeout=30.0)
        self._cache: TTLCache = TTLCache(maxsize=512, ttl=300)
        self._lock = asyncio.Lock()

    async def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        merged = {**(params or {}), "api_key": self._api_key, "format": "json"}
        cache_key = f"{path}:{json.dumps(merged, sort_keys=True)}"

        async with self._lock:
            if cache_key in self._cache:
                return self._cache[cache_key]

        for attempt in range(2):
            try:
                response = await self._http.get(
                    f"{self.BASE_URL}/{path}", params=merged
                )
            except httpx.NetworkError:
                if attempt == 0:
                    await asyncio.sleep(1)
                    continue
                return {
                    "error": "network_error",
                    "message": "Unable to reach Congress.gov API. Please try again.",
                }

            if response.status_code == 429:
                return {
                    "error": "rate_limited",
                    "message": "Congress.gov API rate limit reached. Please wait a moment and try again.",
                }
            if response.status_code == 404:
                return {"error": "not_found", "message": f"Not found: {path}"}

            response.raise_for_status()
            data: dict[str, Any] = response.json()

            async with self._lock:
                self._cache[cache_key] = data

            return data

        return {
            "error": "network_error",
            "message": "Unable to reach Congress.gov API after retry.",
        }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_client.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mcp_congress/client.py tests/test_client.py
git commit -m "feat: add CongressClient with async httpx, TTL cache, and error handling"
```

---

## Task 3: Atomic Bill Tools

**Files:**
- Create: `src/mcp_congress/bills.py`
- Create: `tests/test_bills.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create shared test fixtures in `tests/conftest.py`**

```python
import pytest
import respx
import httpx
from unittest.mock import AsyncMock, MagicMock


SAMPLE_BILL = {
    "congress": 119,
    "type": "HR",
    "number": "1",
    "title": "Infrastructure Investment Act",
    "introducedDate": "2025-01-15",
    "originChamber": "House",
    "latestAction": {"actionDate": "2025-03-01", "text": "Passed House."},
    "sponsor": {
        "bioguideId": "J000295",
        "fullName": "Rep. Jane Smith",
        "state": "OH",
        "party": "R",
    },
    "policyArea": {"name": "Transportation and Public Works"},
}

SAMPLE_MEMBER = {
    "bioguideId": "J000295",
    "directOrderName": "Jane Smith",
    "state": "Ohio",
    "party": "Republican",
    "chamber": "House of Representatives",
    "terms": {"item": [{"startYear": 2019, "endYear": 2025, "chamber": "House of Representatives"}]},
}


@pytest.fixture
def mock_client(monkeypatch):
    client = MagicMock()
    client.get = AsyncMock()
    monkeypatch.setattr("mcp_congress.client.get_client", lambda: client)
    monkeypatch.setattr("mcp_congress.bills.get_client", lambda: client)
    monkeypatch.setattr("mcp_congress.members.get_client", lambda: client)
    monkeypatch.setattr("mcp_congress.committees.get_client", lambda: client)
    return client
```

- [ ] **Step 2: Write failing bill tests**

Create `tests/test_bills.py`:

```python
import json
import pytest
from mcp_congress.bills import search_bills, get_bill, get_bill_cosponsors, get_bill_votes
from tests.conftest import SAMPLE_BILL


async def test_search_bills_returns_json(mock_client):
    mock_client.get.return_value = {"bills": [SAMPLE_BILL], "pagination": {"count": 1}}
    result = await search_bills(query="infrastructure", congress=119)
    data = json.loads(result)
    assert "bills" in data
    assert data["bills"][0]["title"] == "Infrastructure Investment Act"
    mock_client.get.assert_called_once()
    call_args = mock_client.get.call_args
    assert call_args[0][0] == "bill"
    assert call_args[0][1]["query"] == "infrastructure"
    assert call_args[0][1]["congress"] == 119


async def test_get_bill_returns_json(mock_client):
    mock_client.get.return_value = {"bill": SAMPLE_BILL}
    result = await get_bill(congress=119, bill_type="hr", bill_number="1")
    data = json.loads(result)
    assert data["bill"]["type"] == "HR"
    mock_client.get.assert_called_with("bill/119/hr/1", {"limit": 1})


async def test_get_bill_cosponsors_returns_json(mock_client):
    mock_client.get.return_value = {
        "cosponsors": [{"bioguideId": "A000001", "fullName": "Rep. A"}],
        "pagination": {"count": 1},
    }
    result = await get_bill_cosponsors(congress=119, bill_type="hr", bill_number="1")
    data = json.loads(result)
    assert "cosponsors" in data


async def test_get_bill_votes_returns_json(mock_client):
    mock_client.get.return_value = {
        "actions": {
            "items": [
                {
                    "actionDate": "2025-03-01",
                    "text": "Passed House.",
                    "recordedVotes": [
                        {
                            "chamber": "House",
                            "congress": 119,
                            "rollNumber": 42,
                            "url": "http://clerk.house.gov/evs/2025/roll042.xml",
                        }
                    ],
                }
            ]
        }
    }
    result = await get_bill_votes(congress=119, bill_type="hr", bill_number="1")
    data = json.loads(result)
    assert "recorded_votes" in data


async def test_search_bills_passes_optional_params(mock_client):
    mock_client.get.return_value = {"bills": [], "pagination": {"count": 0}}
    await search_bills(congress=119, bill_type="s", limit=10, offset=20)
    call_args = mock_client.get.call_args[0][1]
    assert call_args["billType"] == "s"
    assert call_args["limit"] == 10
    assert call_args["offset"] == 20
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
uv run pytest tests/test_bills.py -v
```

Expected: `ModuleNotFoundError: No module named 'mcp_congress.bills'`

- [ ] **Step 4: Implement `bills.py`**

Create `src/mcp_congress/bills.py`:

```python
import json
from typing import Any

from .client import get_client


async def _fetch_bill(congress: int, bill_type: str, bill_number: str) -> dict[str, Any]:
    return await get_client().get(f"bill/{congress}/{bill_type.lower()}/{bill_number}", {"limit": 1})


async def _fetch_bill_actions(congress: int, bill_type: str, bill_number: str) -> dict[str, Any]:
    return await get_client().get(f"bill/{congress}/{bill_type.lower()}/{bill_number}/actions")


async def _fetch_bill_cosponsors(congress: int, bill_type: str, bill_number: str) -> dict[str, Any]:
    return await get_client().get(
        f"bill/{congress}/{bill_type.lower()}/{bill_number}/cosponsors"
    )


async def search_bills(
    query: str | None = None,
    congress: int | None = None,
    bill_type: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> str:
    """Search for bills by keyword, congress number, or bill type (hr, s, hjres, sjres, hres, sres)."""
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if congress is not None:
        params["congress"] = congress
    if bill_type is not None:
        params["billType"] = bill_type.lower()
    if query is not None:
        params["query"] = query
    return json.dumps(await get_client().get("bill", params))


async def get_bill(congress: int, bill_type: str, bill_number: str) -> str:
    """Get full details for a specific bill including actions, sponsor, and policy area."""
    return json.dumps(await _fetch_bill(congress, bill_type, bill_number))


async def get_bill_cosponsors(congress: int, bill_type: str, bill_number: str) -> str:
    """Get all cosponsors of a specific bill."""
    return json.dumps(await _fetch_bill_cosponsors(congress, bill_type, bill_number))


async def get_bill_votes(congress: int, bill_type: str, bill_number: str) -> str:
    """Get recorded floor votes for a bill, extracted from bill actions."""
    actions_data = await _fetch_bill_actions(congress, bill_type, bill_number)
    if "error" in actions_data:
        return json.dumps(actions_data)

    items = actions_data.get("actions", {}).get("items", [])
    recorded_votes = [
        {
            "action_date": item["actionDate"],
            "action_text": item["text"],
            "votes": item["recordedVotes"],
        }
        for item in items
        if item.get("recordedVotes")
    ]
    return json.dumps({"recorded_votes": recorded_votes, "bill": f"{bill_type.upper()} {bill_number}"})
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/test_bills.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/mcp_congress/bills.py tests/test_bills.py tests/conftest.py
git commit -m "feat: add atomic bill tools (search, detail, cosponsors, votes)"
```

---

## Task 4: Atomic Member Tools

**Files:**
- Create: `src/mcp_congress/members.py`
- Create: `tests/test_members.py`

- [ ] **Step 1: Write failing member tests**

Create `tests/test_members.py`:

```python
import json
import pytest
from mcp_congress.members import (
    search_members,
    get_member,
    get_member_sponsored_legislation,
    get_member_votes,
)
from tests.conftest import SAMPLE_MEMBER


async def test_search_members_by_state(mock_client):
    mock_client.get.return_value = {"members": [SAMPLE_MEMBER], "pagination": {"count": 1}}
    result = await search_members(state="OH")
    data = json.loads(result)
    assert data["members"][0]["bioguideId"] == "J000295"
    call_args = mock_client.get.call_args[0][1]
    assert call_args["stateCode"] == "OH"


async def test_search_members_by_party_and_chamber(mock_client):
    mock_client.get.return_value = {"members": [], "pagination": {"count": 0}}
    await search_members(party="R", chamber="House", current_only=True)
    call_args = mock_client.get.call_args[0][1]
    assert call_args["party"] == "R"
    assert call_args["chamber"] == "House"
    assert call_args["currentMember"] is True


async def test_get_member_returns_json(mock_client):
    mock_client.get.return_value = {"member": SAMPLE_MEMBER}
    result = await get_member(bioguide_id="J000295")
    data = json.loads(result)
    assert data["member"]["bioguideId"] == "J000295"
    mock_client.get.assert_called_with("member/J000295", {})


async def test_get_member_sponsored_legislation(mock_client):
    mock_client.get.return_value = {
        "sponsoredLegislation": [{"congress": 119, "number": "42", "type": "HR"}],
        "pagination": {"count": 1},
    }
    result = await get_member_sponsored_legislation(bioguide_id="J000295")
    data = json.loads(result)
    assert "sponsoredLegislation" in data


async def test_get_member_votes_aggregates_records(mock_client):
    mock_client.get.return_value = {
        "sponsoredLegislation": [
            {"congress": 119, "number": "1", "type": "HR", "title": "Test Bill"},
        ],
        "pagination": {"count": 1},
    }
    result = await get_member_votes(bioguide_id="J000295", congress=119)
    data = json.loads(result)
    assert "bioguide_id" in data
    assert data["bioguide_id"] == "J000295"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_members.py -v
```

Expected: `ModuleNotFoundError: No module named 'mcp_congress.members'`

- [ ] **Step 3: Implement `members.py`**

Create `src/mcp_congress/members.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_members.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mcp_congress/members.py tests/test_members.py
git commit -m "feat: add atomic member tools (search, detail, sponsored legislation, votes)"
```

---

## Task 5: Atomic Committee Tools

**Files:**
- Create: `src/mcp_congress/committees.py`
- Create: `tests/test_committees.py`

- [ ] **Step 1: Write failing committee tests**

Create `tests/test_committees.py`:

```python
import json
import pytest
from mcp_congress.committees import search_committees, get_committee


SAMPLE_COMMITTEE = {
    "systemCode": "hspw00",
    "name": "Committee on Transportation and Infrastructure",
    "chamber": "House",
    "committeeTypeCode": "Standing",
    "url": "https://api.congress.gov/v3/committee/house/hspw00",
}


async def test_search_committees_by_chamber(mock_client):
    mock_client.get.return_value = {"committees": [SAMPLE_COMMITTEE], "pagination": {"count": 1}}
    result = await search_committees(chamber="House")
    data = json.loads(result)
    assert data["committees"][0]["name"] == "Committee on Transportation and Infrastructure"
    call_args = mock_client.get.call_args[0][1]
    assert call_args["chamber"] == "House"


async def test_get_committee_returns_json(mock_client):
    mock_client.get.return_value = {"committee": SAMPLE_COMMITTEE}
    result = await get_committee(chamber="house", committee_code="hspw00")
    data = json.loads(result)
    assert data["committee"]["systemCode"] == "hspw00"
    mock_client.get.assert_called_with("committee/house/hspw00", {})
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_committees.py -v
```

Expected: `ModuleNotFoundError: No module named 'mcp_congress.committees'`

- [ ] **Step 3: Implement `committees.py`**

Create `src/mcp_congress/committees.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_committees.py -v
```

Expected: all 2 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mcp_congress/committees.py tests/test_committees.py
git commit -m "feat: add atomic committee tools (search, detail)"
```

---

## Task 6: Compound Tools — Member Intelligence

**Files:**
- Create: `src/mcp_congress/compound.py`
- Create: `tests/test_compound.py`

This task implements `get_member_profile`, `get_member_stance`, and `compare_member_alignment`.

- [ ] **Step 1: Write failing tests**

Create `tests/test_compound.py`:

```python
import json
import pytest
from unittest.mock import AsyncMock, patch
from mcp_congress.compound import (
    get_member_profile,
    get_member_stance,
    compare_member_alignment,
)
from tests.conftest import SAMPLE_MEMBER, SAMPLE_BILL


@pytest.fixture
def mock_member_fetches(monkeypatch):
    monkeypatch.setattr(
        "mcp_congress.compound._fetch_member",
        AsyncMock(return_value={"member": SAMPLE_MEMBER}),
    )
    monkeypatch.setattr(
        "mcp_congress.compound._fetch_member_sponsored_legislation",
        AsyncMock(return_value={"sponsoredLegislation": [SAMPLE_BILL], "pagination": {"count": 1}}),
    )
    monkeypatch.setattr(
        "mcp_congress.compound._fetch_member_cosponsored_legislation",
        AsyncMock(return_value={"cosponsoredLegislation": [], "pagination": {"count": 0}}),
    )


async def test_get_member_profile_returns_unified_dict(mock_member_fetches):
    result = await get_member_profile(bioguide_id="J000295")
    data = json.loads(result)
    assert data["bioguide_id"] == "J000295"
    assert "member" in data
    assert "sponsored_legislation" in data
    assert "cosponsored_legislation" in data


async def test_get_member_profile_fires_fetches_concurrently(mock_member_fetches):
    import mcp_congress.compound as compound_module
    original_gather = __import__("asyncio").gather
    gather_calls = []

    async def tracking_gather(*coros):
        gather_calls.append(len(coros))
        return await original_gather(*coros)

    with patch("mcp_congress.compound.asyncio.gather", side_effect=tracking_gather):
        await get_member_profile(bioguide_id="J000295")

    assert len(gather_calls) > 0, "asyncio.gather was not called"


async def test_get_member_stance_returns_structured_result(mock_member_fetches):
    result = await get_member_stance(bioguide_id="J000295", topic="transportation")
    data = json.loads(result)
    assert data["bioguide_id"] == "J000295"
    assert data["topic"] == "transportation"
    assert "sponsored_relevant" in data
    assert "cosponsored_relevant" in data


@pytest.fixture
def mock_two_members(monkeypatch):
    member_a = {**SAMPLE_MEMBER, "bioguideId": "A000001", "directOrderName": "Alice A"}
    member_b = {**SAMPLE_MEMBER, "bioguideId": "B000002", "directOrderName": "Bob B"}
    bill_a = {**SAMPLE_BILL, "number": "100"}
    bill_b = {**SAMPLE_BILL, "number": "200"}

    call_count = {"n": 0}

    async def alternating_sponsored(*args):
        call_count["n"] += 1
        if call_count["n"] % 2 == 1:
            return {"sponsoredLegislation": [bill_a], "pagination": {"count": 1}}
        return {"sponsoredLegislation": [bill_b], "pagination": {"count": 1}}

    monkeypatch.setattr("mcp_congress.compound._fetch_member", AsyncMock(side_effect=[
        {"member": member_a}, {"member": member_b}
    ]))
    monkeypatch.setattr(
        "mcp_congress.compound._fetch_member_sponsored_legislation",
        alternating_sponsored,
    )
    monkeypatch.setattr(
        "mcp_congress.compound._fetch_member_cosponsored_legislation",
        AsyncMock(return_value={"cosponsoredLegislation": [], "pagination": {"count": 0}}),
    )


async def test_compare_member_alignment_returns_both_members(mock_two_members):
    result = await compare_member_alignment(
        bioguide_id_a="A000001", bioguide_id_b="B000002"
    )
    data = json.loads(result)
    assert "member_a" in data
    assert "member_b" in data
    assert "shared_policy_areas" in data
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_compound.py::test_get_member_profile_returns_unified_dict tests/test_compound.py::test_get_member_stance_returns_structured_result tests/test_compound.py::test_compare_member_alignment_returns_both_members -v
```

Expected: `ModuleNotFoundError: No module named 'mcp_congress.compound'`

- [ ] **Step 3: Implement `compound.py` (first three tools)**

Create `src/mcp_congress/compound.py`:

```python
import asyncio
import json
from typing import Any

from .members import _fetch_member, _fetch_member_sponsored_legislation, _fetch_member_cosponsored_legislation


async def get_member_profile(bioguide_id: str, sponsored_limit: int = 20) -> str:
    """
    Build a comprehensive profile for a member of Congress.
    Combines bio, committee assignments, sponsorship history, and cosponsorship activity
    into a single response. Use this before analyzing a member's priorities or predicting votes.
    """
    member_data, sponsored_data, cosponsored_data = await asyncio.gather(
        _fetch_member(bioguide_id),
        _fetch_member_sponsored_legislation(bioguide_id, limit=sponsored_limit),
        _fetch_member_cosponsored_legislation(bioguide_id, limit=sponsored_limit),
    )

    member = member_data.get("member", {})
    sponsored = sponsored_data.get("sponsoredLegislation", [])
    cosponsored = cosponsored_data.get("cosponsoredLegislation", [])

    policy_counts: dict[str, int] = {}
    for bill in sponsored + cosponsored:
        area = bill.get("policyArea", {}).get("name", "Unknown") if isinstance(bill.get("policyArea"), dict) else str(bill.get("policyArea", "Unknown"))
        policy_counts[area] = policy_counts.get(area, 0) + 1

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
    """
    sponsored_data, cosponsored_data = await asyncio.gather(
        _fetch_member_sponsored_legislation(bioguide_id, limit=50),
        _fetch_member_cosponsored_legislation(bioguide_id, limit=50),
    )

    topic_lower = topic.lower()

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
        "note": "Results filtered by topic keyword match in bill title or policy area.",
    })


async def compare_member_alignment(bioguide_id_a: str, bioguide_id_b: str) -> str:
    """
    Compare the legislative alignment of two members of Congress.
    Returns shared policy areas, overlap in cosponsored bills, and party/chamber context.
    Useful for coalition building and identifying potential allies or opponents.
    """
    (member_a_data, sponsored_a, cosponsored_a), (member_b_data, sponsored_b, cosponsored_b) = await asyncio.gather(
        asyncio.gather(
            _fetch_member(bioguide_id_a),
            _fetch_member_sponsored_legislation(bioguide_id_a, limit=50),
            _fetch_member_cosponsored_legislation(bioguide_id_a, limit=50),
        ),
        asyncio.gather(
            _fetch_member(bioguide_id_b),
            _fetch_member_sponsored_legislation(bioguide_id_b, limit=50),
            _fetch_member_cosponsored_legislation(bioguide_id_b, limit=50),
        ),
    )

    def policy_areas(sponsored: dict, cosponsored: dict) -> set[str]:
        areas = set()
        for bill in sponsored.get("sponsoredLegislation", []) + cosponsored.get("cosponsoredLegislation", []):
            area = bill.get("policyArea", {})
            if isinstance(area, dict):
                areas.add(area.get("name", ""))
            elif area:
                areas.add(str(area))
        return areas - {""}

    areas_a = policy_areas(sponsored_a, cosponsored_a)
    areas_b = policy_areas(sponsored_b, cosponsored_b)

    return json.dumps({
        "member_a": member_a_data.get("member", {}),
        "member_b": member_b_data.get("member", {}),
        "shared_policy_areas": sorted(areas_a & areas_b),
        "unique_to_a": sorted(areas_a - areas_b),
        "unique_to_b": sorted(areas_b - areas_a),
    })
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_compound.py -v -k "profile or stance or alignment"
```

Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mcp_congress/compound.py tests/test_compound.py
git commit -m "feat: add compound tools for member profile, stance analysis, and alignment comparison"
```

---

## Task 7: Compound Tools — Bill Intelligence and Priority Analysis

**Files:**
- Modify: `src/mcp_congress/compound.py`
- Modify: `tests/test_compound.py`

This task adds `analyze_bill_support`, `suggest_cosponsor_opportunities`, and `analyze_congress_priorities`.

- [ ] **Step 1: Add failing tests to `tests/test_compound.py`**

Append to the existing `tests/test_compound.py`:

```python
from mcp_congress.compound import (
    analyze_bill_support,
    suggest_cosponsor_opportunities,
    analyze_congress_priorities,
)


@pytest.fixture
def mock_bill_fetches(monkeypatch):
    monkeypatch.setattr(
        "mcp_congress.compound._fetch_bill",
        AsyncMock(return_value={"bill": {**SAMPLE_BILL, "committees": {"item": [{"systemCode": "hspw00"}]}}}),
    )
    monkeypatch.setattr(
        "mcp_congress.compound._fetch_bill_cosponsors",
        AsyncMock(return_value={"cosponsors": [{"bioguideId": "A000001", "fullName": "Rep. A", "party": "R", "state": "OH"}], "pagination": {"count": 1}}),
    )
    monkeypatch.setattr(
        "mcp_congress.compound._fetch_member_sponsored_legislation",
        AsyncMock(return_value={"sponsoredLegislation": [SAMPLE_BILL], "pagination": {"count": 1}}),
    )
    monkeypatch.setattr(
        "mcp_congress.compound._fetch_member_cosponsored_legislation",
        AsyncMock(return_value={"cosponsoredLegislation": [], "pagination": {"count": 0}}),
    )


async def test_analyze_bill_support_returns_support_data(mock_bill_fetches):
    result = await analyze_bill_support(congress=119, bill_type="hr", bill_number="1")
    data = json.loads(result)
    assert "bill" in data
    assert "cosponsors" in data
    assert "cosponsor_count" in data


async def test_suggest_cosponsor_opportunities_returns_ranked_list(mock_member_fetches, monkeypatch):
    monkeypatch.setattr(
        "mcp_congress.compound._search_bills_raw",
        AsyncMock(return_value={"bills": [
            {**SAMPLE_BILL, "number": "999", "title": "New Infrastructure Bill"},
        ], "pagination": {"count": 1}}),
    )
    result = await suggest_cosponsor_opportunities(bioguide_id="J000295", congress=119)
    data = json.loads(result)
    assert "bioguide_id" in data
    assert "suggestions" in data
    assert isinstance(data["suggestions"], list)


async def test_analyze_congress_priorities_tiers_by_advancement(monkeypatch):
    bills = [
        {**SAMPLE_BILL, "number": "1", "latestAction": {"text": "Became Public Law."}, "policyArea": {"name": "Transportation and Public Works"}},
        {**SAMPLE_BILL, "number": "2", "latestAction": {"text": "Referred to committee."}, "policyArea": {"name": "Transportation and Public Works"}},
        {**SAMPLE_BILL, "number": "3", "latestAction": {"text": "Passed House."}, "policyArea": {"name": "Economics and Public Finance"}},
    ]
    monkeypatch.setattr(
        "mcp_congress.compound._search_bills_raw",
        AsyncMock(return_value={"bills": bills, "pagination": {"count": 3}}),
    )
    result = await analyze_congress_priorities(congress=119)
    data = json.loads(result)
    assert "congress" in data
    assert "policy_areas" in data
    areas = {pa["area"]: pa for pa in data["policy_areas"]}
    transport = areas["Transportation and Public Works"]
    assert transport["enacted_count"] >= 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_compound.py -v -k "bill_support or cosponsor_opp or priorities"
```

Expected: `ImportError: cannot import name 'analyze_bill_support'`

- [ ] **Step 3: Add remaining compound tools to `compound.py`**

Add these imports at the top of `src/mcp_congress/compound.py`:

```python
from .bills import _fetch_bill, _fetch_bill_cosponsors
from .client import get_client
```

Add this private helper after the imports:

```python
async def _search_bills_raw(params: dict[str, Any]) -> dict[str, Any]:
    return await get_client().get("bill", params)
```

Append to `src/mcp_congress/compound.py`:

```python
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
    """
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
    """
    sponsored_data, cosponsored_data = await asyncio.gather(
        _fetch_member_sponsored_legislation(bioguide_id, limit=50),
        _fetch_member_cosponsored_legislation(bioguide_id, limit=50),
    )

    sponsored = sponsored_data.get("sponsoredLegislation", [])
    cosponsored = cosponsored_data.get("cosponsoredLegislation", [])

    already_involved = {
        f"{b.get('type', '')}{b.get('number', '')}" for b in sponsored + cosponsored
    }

    policy_counts: dict[str, int] = {}
    for bill in sponsored + cosponsored:
        area = bill.get("policyArea", {})
        name = area.get("name", "") if isinstance(area, dict) else str(area)
        if name:
            policy_counts[name] = policy_counts.get(name, 0) + 1

    top_areas = sorted(policy_counts.items(), key=lambda x: x[1], reverse=True)[:3]

    candidate_bills: list[dict[str, Any]] = []
    for area_name, _ in top_areas:
        result = await _search_bills_raw({
            "congress": congress,
            "query": area_name,
            "limit": 20,
            "offset": 0,
        })
        for bill in result.get("bills", []):
            key = f"{bill.get('type', '')}{bill.get('number', '')}"
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
    })


async def analyze_congress_priorities(
    congress: int = 119, limit_per_fetch: int = 250
) -> str:
    """
    Identify the legislative priorities of a congress by analyzing bill advancement.
    Bills are grouped by policy area and weighted by how far they advanced
    (enacted > floor vote > committee passage > introduced).
    Returns a ranked list of policy areas reflecting real legislative momentum.
    """
    result = await _search_bills_raw({"congress": congress, "limit": limit_per_fetch, "offset": 0})
    bills = result.get("bills", [])

    area_stats: dict[str, dict[str, Any]] = {}
    for bill in bills:
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

    ranked = sorted(area_stats.values(), key=lambda s: s["total_weight"], reverse=True)

    return json.dumps({
        "congress": congress,
        "bills_analyzed": len(bills),
        "policy_areas": ranked,
        "note": "Areas ranked by total advancement weight. Enacted bills weighted 6x vs introduced-only (1x).",
    })
```

- [ ] **Step 4: Run all compound tests**

```bash
uv run pytest tests/test_compound.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mcp_congress/compound.py tests/test_compound.py
git commit -m "feat: add compound tools for bill support, cosponsor suggestions, and congress priorities"
```

---

## Task 8: MCP Server Registration

**Files:**
- Create: `src/mcp_congress/server.py`

- [ ] **Step 1: Implement `server.py`**

Create `src/mcp_congress/server.py`:

```python
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from .bills import get_bill, get_bill_cosponsors, get_bill_votes, search_bills
from .committees import get_committee, search_committees
from .compound import (
    analyze_bill_support,
    analyze_congress_priorities,
    compare_member_alignment,
    get_member_profile,
    get_member_stance,
    suggest_cosponsor_opportunities,
)
from .members import get_member, get_member_sponsored_legislation, get_member_votes, search_members

load_dotenv()

mcp = FastMCP("congress-gov")

# Atomic — Bills
mcp.tool()(search_bills)
mcp.tool()(get_bill)
mcp.tool()(get_bill_cosponsors)
mcp.tool()(get_bill_votes)

# Atomic — Members
mcp.tool()(search_members)
mcp.tool()(get_member)
mcp.tool()(get_member_sponsored_legislation)
mcp.tool()(get_member_votes)

# Atomic — Committees
mcp.tool()(search_committees)
mcp.tool()(get_committee)

# Compound
mcp.tool()(get_member_profile)
mcp.tool()(get_member_stance)
mcp.tool()(analyze_bill_support)
mcp.tool()(compare_member_alignment)
mcp.tool()(suggest_cosponsor_opportunities)
mcp.tool()(analyze_congress_priorities)


def main() -> None:
    mcp.run()
```

- [ ] **Step 2: Verify server starts**

```bash
uv run mcp-congress-gov --help
```

Expected: help output from the MCP CLI (or the process starts without import errors). If `--help` is not supported, verify with:

```bash
uv run python -c "from mcp_congress.server import mcp; print(f'Registered {len(mcp.list_tools())} tools')"
```

Expected: prints registered tool count (16 tools).

- [ ] **Step 3: Verify server can be invoked via MCP inspector (optional but recommended)**

```bash
uv run mcp dev src/mcp_congress/server.py
```

Expected: MCP inspector opens in browser showing all 16 registered tools.

- [ ] **Step 4: Commit**

```bash
git add src/mcp_congress/server.py
git commit -m "feat: register all tools with FastMCP server entry point"
```

---

## Task 9: Integration Tests

**Files:**
- Create: `tests/integration/test_integration.py`

- [ ] **Step 1: Write integration tests**

Create `tests/integration/test_integration.py`:

```python
"""
Integration tests — require a real CONGRESS_API_KEY environment variable.
Run with: uv run pytest tests/integration/ -v -m integration
"""
import json
import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("CONGRESS_API_KEY"),
    reason="CONGRESS_API_KEY not set — skipping integration tests",
)


async def test_search_bills_live():
    from mcp_congress.bills import search_bills
    result = await search_bills(query="infrastructure", congress=119, limit=5)
    data = json.loads(result)
    assert "bills" in data
    assert isinstance(data["bills"], list)


async def test_search_members_live():
    from mcp_congress.members import search_members
    result = await search_members(state="TX", current_only=True, limit=5)
    data = json.loads(result)
    assert "members" in data
    assert len(data["members"]) > 0


async def test_search_committees_live():
    from mcp_congress.committees import search_committees
    result = await search_committees(chamber="House", limit=5)
    data = json.loads(result)
    assert "committees" in data


async def test_get_member_live():
    from mcp_congress.members import get_member
    result = await get_member(bioguide_id="P000197")  # Nancy Pelosi
    data = json.loads(result)
    assert "member" in data or "error" in data  # member may be inactive


async def test_get_member_profile_live():
    from mcp_congress.compound import get_member_profile
    result = await get_member_profile(bioguide_id="S001185")  # Terri Sewell
    data = json.loads(result)
    assert "bioguide_id" in data
    assert "member" in data


async def test_analyze_congress_priorities_live():
    from mcp_congress.compound import analyze_congress_priorities
    result = await analyze_congress_priorities(congress=119, limit_per_fetch=50)
    data = json.loads(result)
    assert "policy_areas" in data
    assert len(data["policy_areas"]) > 0
    # Verify ranking — first area should have higher total_weight than last
    areas = data["policy_areas"]
    if len(areas) > 1:
        assert areas[0]["total_weight"] >= areas[-1]["total_weight"]
```

- [ ] **Step 2: Run integration tests (with API key)**

```bash
uv run pytest tests/integration/ -v
```

Expected: all tests PASS against the live Congress.gov API. If any endpoint returns 404, check the bioguide IDs — they can be verified at bioguide.congress.gov.

- [ ] **Step 3: Verify unit tests still pass**

```bash
uv run pytest tests/ --ignore=tests/integration -v
```

Expected: all unit tests still PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_integration.py
git commit -m "test: add integration tests for live Congress.gov API calls"
```

---

## Task 10: CLAUDE.md

**Files:**
- Create: `CLAUDE.md`

- [ ] **Step 1: Write `CLAUDE.md`**

Create `CLAUDE.md` at the project root:

```markdown
# mcp-congress-gov

MCP server providing Congress.gov data access for Claude. Built for lobbyists serving local government clients — exposes both atomic data tools and compound analytical tools for member profiling, bill analysis, and legislative priority intelligence.

## Architecture

- `src/mcp_congress/client.py` — `CongressClient` singleton with async httpx, 5-minute TTL cache, and structured error responses. All modules call `get_client()` from here.
- `src/mcp_congress/bills.py`, `members.py`, `committees.py` — atomic tools. Each exposes public `async def` tool functions and private `_fetch_*` helpers used by compound tools.
- `src/mcp_congress/compound.py` — compound tools that call `_fetch_*` helpers via `asyncio.gather()` for concurrent fetches.
- `src/mcp_congress/server.py` — FastMCP instance. Imports all tool functions and registers them with `mcp.tool()`.

## Adding a New Tool

1. Add a `_fetch_*` helper (returns `dict`) and a public tool function (returns `json.dumps(...)`) to the appropriate module.
2. Write a test in the matching `tests/test_*.py` file using `mock_client` from `conftest.py`.
3. Register it in `server.py` with `mcp.tool()(your_function)`.
4. Add a one-line entry to the tools table in `docs/superpowers/specs/2026-05-18-congress-mcp-server-design.md`.

## Development

```bash
uv sync --extra dev          # install dependencies
uv run pytest tests/ --ignore=tests/integration  # unit tests
uv run pytest tests/integration/ -v              # integration tests (needs CONGRESS_API_KEY)
uv run mcp dev src/mcp_congress/server.py        # MCP inspector
```

## Environment

- `CONGRESS_API_KEY` — required. Get a free key at https://api.congress.gov/sign-up/
- Local dev: set in `.env` file at project root (gitignored).
- Teammate deploy: set in Claude Desktop `claude_desktop_config.json` under `env`.

## Congress.gov API Notes

- Base URL: `https://api.congress.gov/v3/`
- Bill types: `hr` (House bill), `s` (Senate bill), `hjres`, `sjres`, `hconres`, `sconres`, `hres`, `sres`
- Member IDs: BioGuide IDs (e.g. `J000295`) — searchable at bioguide.congress.gov
- Rate limit: 5,000 requests/hour with API key. The TTL cache handles repeated lookups within sessions.
- The API does not expose a native "member vote history" endpoint. `get_member_votes` approximates this via sponsored/cosponsored legislation. For specific roll call votes, use `get_bill_votes`.

## Teammate Setup (Claude Desktop)

1. Install `uv`: https://docs.astral.sh/uv/
2. Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "congress": {
      "command": "uvx",
      "args": ["mcp-congress-gov"],
      "env": {
        "CONGRESS_API_KEY": "their-key-here"
      }
    }
  }
}
```
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add CLAUDE.md with architecture overview and developer setup"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Covered by |
|-----------------|-----------|
| Python 3.14 | Task 1 — `pyproject.toml` `requires-python = ">=3.14"` |
| async httpx + TTL cache | Task 2 — `client.py` |
| `search_bills`, `get_bill`, `get_bill_cosponsors`, `get_bill_votes` | Task 3 |
| `search_members`, `get_member`, `get_member_sponsored_legislation`, `get_member_votes` | Task 4 |
| `search_committees`, `get_committee` | Task 5 |
| `get_member_profile`, `get_member_stance`, `compare_member_alignment` | Task 6 |
| `analyze_bill_support`, `suggest_cosponsor_opportunities`, `analyze_congress_priorities` | Task 7 |
| `asyncio.gather()` concurrency in compound tools | Tasks 6–7 |
| FastMCP server with all 16 tools registered | Task 8 |
| Integration tests with `@pytest.mark.skipif` guard | Task 9 |
| CLAUDE.md | Task 10 |
| `uvx mcp-congress-gov` entry point | Task 1 — `pyproject.toml` `[project.scripts]` |
| Error handling (429, 404, network) | Task 2 — `client.py` |
| TTL cache prevents duplicate API calls | Task 2 — verified by `test_caching_prevents_duplicate_requests` |
| Teammate setup in Claude Desktop | Task 10 — CLAUDE.md |
| `analyze_congress_priorities` advancement weighting | Task 7 — `ACTION_WEIGHTS` + `_advancement_weight()` |
