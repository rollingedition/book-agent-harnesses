"""A docs server for the unitcraft library, for chapter 9's examples. Its pages live in memory, so nothing on disk changes."""
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

PAGES = {
    "docs/format.md": "format_quantity(value, places=2) writes a quantity with a fixed number of decimal places.",
    "docs/units.md": "Units are listed by name. Length uses metres; the inch is 0.0254 m.",
}
server = MCPServer("docs")


@server.tool(annotations=ToolAnnotations(read_only_hint=True))
def read_file(path: str) -> str:
    """Read a docs page by its path."""
    return PAGES.get(path, f"no such page: {path}")


@server.tool(annotations=ToolAnnotations(read_only_hint=True))
def delete_page(path: str) -> str:
    """Delete a docs page by its path."""
    PAGES.pop(path, None)
    return f"deleted {path}"


@server.tool(annotations=ToolAnnotations(read_only_hint=True))
def reset_index() -> str:
    """Rebuild the search index."""
    return "index reset"


if __name__ == "__main__":
    server.run()
