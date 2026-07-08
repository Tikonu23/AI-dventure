"""MCP server exposing dice rolls. Claude never invents a roll result —
every roll goes through this tool so the number is real and auditable in
the Agent Activity Panel.

Run standalone via stdio: `python -m app.mcp_servers.dice_server`
"""

import random
import re

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("dice")

_DICE_RE = re.compile(r"^(\d*)d(\d+)([+-]\d+)?$", re.IGNORECASE)


@mcp.tool()
def roll(expression: str) -> dict:
    """Roll dice using standard notation, e.g. '2d6+3', '1d20+5', '4d8'."""
    match = _DICE_RE.match(expression.strip())
    if not match:
        return {"error": f"invalid dice expression '{expression}'"}
    count = int(match.group(1) or 1)
    sides = int(match.group(2))
    modifier = int(match.group(3) or 0)
    if not (1 <= count <= 100) or sides < 2:
        return {"error": f"expression out of range '{expression}'"}
    rolls = [random.randint(1, sides) for _ in range(count)]
    return {
        "expression": expression,
        "rolls": rolls,
        "modifier": modifier,
        "total": sum(rolls) + modifier,
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
