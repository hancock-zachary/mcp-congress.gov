# Congress.gov MCP Server — Design Spec

**Date:** 2026-05-18
**Status:** Approved

## Overview

An MCP server that gives lobbyists working on behalf of local government entities fast, intelligent access to Congress.gov data directly from Claude Desktop (and Claude Code / Claude Cowork). The server exposes both atomic data-fetch tools and compound analytical tools designed around real lobbying workflows: member profiling, bill support analysis, cosponsor opportunity identification, and congressional priority intelligence.

---

## Architecture

### Runtime & Distribution

- **Language:** Python 3.11+
- **Distribution:** PyPI package, runnable via `uvx mcp-congress-gov` — no Python install required for end users
- **Auth:** `CONGRESS_API_KEY` environment variable, set once in Claude Desktop config JSON
- **End-user setup:** Two steps — install `uv`, paste a config snippet into `claude_desktop_config.json`

### Project Structure

```
mcp-congress-gov/
├── pyproject.toml          # package metadata + uvx entry point
├── .env                    # dev-only API key (gitignored)
├── CLAUDE.md               # developer documentation
└── src/
    └── mcp_congress/
        ├── __init__.py
        ├── server.py       # MCP server entry point, tool registration
        ├── client.py       # async httpx client + TTL cache + rate limit handling
        ├── bills.py        # atomic bill tools
        ├── members.py      # atomic member tools
        ├── votes.py        # atomic vote tools
        ├── committees.py   # atomic committee tools
        └── compound.py     # multi-source analytical tools
```

### Key Dependencies

| Package | Purpose |
|---------|---------|
| `mcp[cli]` | MCP server framework |
| `httpx` | Async HTTP client |
| `cachetools` | In-memory TTL cache |
| `python-dotenv` | Load `.env` for local dev |
| `pytest` | Testing |
| `pytest-asyncio` | Async test support |

---

## Tools

### Atomic Tools

Single-endpoint fetches. Building blocks for both Claude's reasoning and the compound tools.

| Tool | Description |
|------|-------------|
| `search_bills` | Search by keyword, congress number, status, sponsor, subject area |
| `get_bill` | Full bill detail — actions, titles, sponsors, cosponsors, subjects |
| `search_members` | Find members by name, state, party, chamber |
| `get_member` | Member bio, terms served, party history, official contact |
| `get_member_sponsored_legislation` | Bills a member has sponsored or cosponsored |
| `get_bill_cosponsors` | All cosponsors of a specific bill |
| `get_member_votes` | A member's voting history with bill context |
| `get_bill_votes` | How every member voted on a specific bill |
| `search_committees` | Find committees by chamber or name |
| `get_committee` | Committee details and current membership |

### Compound Tools

Multi-call analytical tools built for core lobbying workflows.

| Tool | Description |
|------|-------------|
| `get_member_profile` | Combines bio, committee assignments, sponsorship patterns, and recent voting record into a unified summary |
| `get_member_stance` | Given a member and a policy topic, synthesizes their position from votes, sponsorships, and committee work |
| `analyze_bill_support` | For a given bill, identifies likely supporters and opponents among relevant members based on past votes and committee assignments |
| `compare_member_alignment` | Given two members, shows where they vote together vs. diverge — useful for coalition building |
| `suggest_cosponsor_opportunities` | Given a member, finds active bills aligned with their sponsorship history, voting record, and committee focus areas — returns ranked suggestions with reasoning |
| `analyze_congress_priorities` | For a given congress (e.g., 119th), aggregates bills by policy area and weights by advancement stage — surfaces what's actually moving vs. just being proposed |

#### `analyze_congress_priorities` Weighting

Bills ranked by advancement stage, highest to lowest:

1. Enacted into law
2. Passed both chambers
3. Passed one chamber / received floor vote
4. Passed out of committee
5. Reported by committee
6. Introduced only

---

## Data Flow & Client

### `CongressClient` (`client.py`)

- Single class wrapping `httpx.AsyncClient`
- Base URL: `https://api.congress.gov/v3/`
- API key injected from `CONGRESS_API_KEY` env var on initialization
- TTL cache (5-minute default) keyed on endpoint + params — prevents redundant API calls within a session
- All fetch methods are `async`

### Compound Tool Concurrency

Compound tools use `asyncio.gather()` to fire multiple atomic fetches concurrently rather than sequentially.

Example — `get_member_profile`:
```
get_member_profile("bioguideId")
  ├── get_member()                       ─┐
  ├── get_member_sponsored_legislation() ─┤ concurrent via asyncio.gather()
  ├── get_member_votes()                 ─┤
  └── get_committee() × N               ─┘
      └── assembled into unified profile dict
```

This turns a ~5s sequential chain into a ~1s concurrent fetch for the typical member profile.

### Error Handling

| Condition | Behavior |
|-----------|----------|
| HTTP 429 (rate limit) | Return structured error with clear message — Claude surfaces it to the user |
| HTTP 404 (not found) | Return structured "not found" response — no exception raised |
| Network error | Single retry with 1s backoff, then raise with readable message |

---

## Packaging & Distribution

### `pyproject.toml` Entry Point

```toml
[project.scripts]
mcp-congress-gov = "mcp_congress.server:main"
```

### Teammate Setup (One Time)

**Step 1:** Install `uv` — single command at `https://docs.astral.sh/uv/`

**Step 2:** Add to `claude_desktop_config.json`:

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

Restart Claude Desktop. No further steps.

### Developer Setup

Uses `.env` file at project root (gitignored) with `CONGRESS_API_KEY=...`. Run locally with `uv run mcp-congress-gov` or via MCP inspector for tool testing.

---

## Testing

### Unit Tests (`pytest` + `pytest-asyncio`)

- Each atomic tool tested against mocked `httpx` responses
- Verify correct endpoint construction and response parsing
- TTL cache behavior — repeated calls hit cache, not the network
- Error conditions — 404, 429, network failure return expected structured responses

### Integration Tests (opt-in)

- Marked `@pytest.mark.integration`
- Make real Congress.gov API calls
- One happy-path call per tool category
- Skipped automatically unless `CONGRESS_API_KEY` is present in the environment
- Cover compound tools end-to-end

Compound tool orchestration logic is not unit-tested in isolation — the value is in the assembled data, which integration tests verify against real API responses.
