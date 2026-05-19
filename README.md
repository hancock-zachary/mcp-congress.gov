# mcp-congress-gov

An MCP server that gives Claude direct access to Congress.gov data. Search bills, look up members, explore committees, and run compound analytical queries — like predicting how a member will vote on a bill or identifying which issues a congress member prioritizes.

Built for teams that work with Congress.gov regularly and want Claude to answer legislative questions without copy-pasting data manually.

---

## What It Does

**Atomic tools** — pull raw data from Congress.gov:

| Tool | What it fetches |
|------|----------------|
| `search_bills` | Bills by keyword, congress, type, or status |
| `get_bill` | Full bill detail — actions, sponsors, subjects |
| `get_bill_cosponsors` | All cosponsors of a specific bill |
| `get_bill_votes` | Recorded floor votes extracted from bill actions |
| `search_members` | Members by name, state, party, or chamber |
| `get_member` | Bio, terms, party history, contact info |
| `get_member_sponsored_legislation` | Bills a member has sponsored |
| `get_member_votes` | Member's voting activity via sponsored/cosponsored legislation |
| `search_committees` | Committees by chamber or name |
| `get_committee` | Committee details and membership |

**Compound tools** — multi-source analytical queries:

| Tool | What it does |
|------|-------------|
| `get_member_profile` | Full member profile: bio + committees + sponsorship patterns + voting activity |
| `get_member_stance` | Member's synthesized position on a policy topic |
| `analyze_bill_support` | Cosponsors, party breakdown, and state distribution for a bill |
| `compare_member_alignment` | How two members align or diverge across policy areas |
| `suggest_cosponsor_opportunities` | Active bills a member is well-positioned to cosponsor |
| `analyze_congress_priorities` | Policy areas ranked by real legislative momentum for a given congress |

---

## Requirements

- [uv](https://docs.astral.sh/uv/) — a fast Python package manager (replaces pip/virtualenv)
- A Congress.gov API key — free at [api.congress.gov/sign-up](https://api.congress.gov/sign-up/)
- Claude Desktop, Claude Code, or Claude Cowork

---

## Installation

### Step 1 — Clone this repository

```bash
git clone https://github.com/hancock-zachary/mcp-congress.gov.git
```

Note the folder path where you cloned it — you'll need it in Step 4.

### Step 2 — Install uv

**macOS / Linux:**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows (PowerShell):**
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Restart your terminal after installing.

### Step 3 — Get a Congress.gov API key

Sign up at [api.congress.gov/sign-up](https://api.congress.gov/sign-up/). The key arrives by email within a few minutes.

### Step 4 — Configure Claude Desktop

Open your Claude Desktop configuration file:

- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

Add the following inside the `"mcpServers"` object (create the object if it doesn't exist):

**macOS / Linux:**
```json
{
  "mcpServers": {
    "Congress.gov MCP": {
      "command": "uvx",
      "args": ["--from", "/path/to/mcp-congress.gov", "mcp-congress-gov"],
      "env": {
        "CONGRESS_API_KEY": "your-api-key-here"
      }
    }
  }
}
```

**Windows:**
```json
{
  "mcpServers": {
    "Congress.gov MCP": {
      "command": "uvx",
      "args": ["--from", "C:\\Users\\yourname\\Documents\\GitHub\\mcp-congress.gov", "mcp-congress-gov"],
      "env": {
        "CONGRESS_API_KEY": "your-api-key-here"
      }
    }
  }
}
```

Replace the path with the folder where you cloned the repo in Step 1, and replace `your-api-key-here` with the key from Step 3.

> **Windows path tip:** In File Explorer, open the cloned folder and copy the path from the address bar. Then replace every `\` with `\\` in the config.

### Step 5 — Restart Claude Desktop

Quit and reopen Claude Desktop. The Congress.gov tools will appear automatically.

---

## Usage Examples

Once installed, ask Claude things like:

- *"What bills has Senator John Cornyn sponsored in the 119th Congress?"*
- *"Who are the cosponsors of HR 1 in the 119th Congress?"*
- *"Build a full profile for member with BioGuide ID S001185."*
- *"What are the top legislative priorities of the 119th Congress based on what's actually passed committee?"*
- *"Suggest bills that Rep. Jane Smith would be a good fit to cosponsor based on her record."*
- *"How aligned are these two members on infrastructure and transportation?"*

---

## Configuring for Claude Code or Claude Cowork

Claude Code uses a `.mcp.json` file or the `--mcp-config` flag. Add the same `mcpServers` block to your project's `.mcp.json`, using the same local path as above:

**macOS / Linux:**
```json
{
  "mcpServers": {
    "congress": {
      "command": "uvx",
      "args": ["--from", "/path/to/mcp-congress.gov", "mcp-congress-gov"],
      "env": {
        "CONGRESS_API_KEY": "your-api-key-here"
      }
    }
  }
}
```

**Windows:**
```json
{
  "mcpServers": {
    "congress": {
      "command": "uvx",
      "args": ["--from", "C:\\Users\\yourname\\Documents\\GitHub\\mcp-congress.gov", "mcp-congress-gov"],
      "env": {
        "CONGRESS_API_KEY": "your-api-key-here"
      }
    }
  }
}
```

---

## API Key Notes

- Rate limit: **5,000 requests/hour** with a key (1,000/hour without)
- The server caches responses for 5 minutes — repeated lookups for the same member or bill won't count against your limit
- Compound tools make multiple API calls per request; `get_member_profile` typically uses 3 calls, `suggest_cosponsor_opportunities` uses up to 5

---

## Member BioGuide IDs

Many tools require a BioGuide ID (e.g. `S001185`, `C001075`). Look these up at [bioguide.congress.gov](https://bioguide.congress.gov/) or use `search_members` first to find the ID.

---

## Bill Identifiers

Bills are identified by congress number, type, and number:

| Field | Example | Options |
|-------|---------|---------|
| Congress | `119` | Current congress number |
| Type | `hr` | `hr`, `s`, `hjres`, `sjres`, `hconres`, `sconres`, `hres`, `sres` |
| Number | `1` | The bill number |

---

## Troubleshooting

**Tools don't appear in Claude Desktop**
- Verify the JSON in `claude_desktop_config.json` is valid (no trailing commas, balanced braces)
- Make sure `uv` is installed and accessible: open a terminal and run `uv --version`
- Restart Claude Desktop after any config change

**"CONGRESS_API_KEY environment variable is not set"**
- Double-check the key is in the `"env"` block of your config, not somewhere else
- Make sure there are no extra spaces around the key value

**Rate limit errors**
- The server will return a clear message when the limit is hit
- Wait a minute and retry, or check your usage at [api.congress.gov](https://api.congress.gov/)
