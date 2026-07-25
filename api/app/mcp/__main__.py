"""`python -m app.mcp` — run the SyncUp MCP server over stdio."""

from app.mcp.server import mcp

if __name__ == "__main__":
    mcp.run(transport="stdio")
