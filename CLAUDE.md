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

## Policy-Area Cache

`src/mcp_congress/data/policy_areas.json` is a bundled cache mapping bill keys to CRS policy areas. It is committed to the repo so teammates get pre-seeded data on first install. The cache refreshes automatically at runtime when it is more than 24 hours old.

To do a full initial seed (or re-seed after a long gap), run:

```bash
uv run python src/mcp_congress/seed/seed_policy_areas.py                        # seed 119th Congress
uv run python src/mcp_congress/seed/seed_policy_areas.py --congresses 118 119  # seed multiple congresses
```

Commit the updated `policy_areas.json` afterward to share the new mappings with the team.

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
