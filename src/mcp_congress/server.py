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
