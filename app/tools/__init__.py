"""Tool registry.

Register new integrations here; the rest of the application discovers tools
through :func:`get_tool` and :func:`all_tools`.
"""

from __future__ import annotations

from app.tools.base import BuiltCommand, SecurityTool, ToolError, ToolStatus
from app.tools.ffuf import FfufTool
from app.tools.katana import KatanaTool

TOOL_CLASSES: dict[str, type[SecurityTool]] = {
    FfufTool.slug: FfufTool,
    KatanaTool.slug: KatanaTool,
}


def get_tool(slug: str, binary: str | None = None) -> SecurityTool:
    try:
        tool_class = TOOL_CLASSES[slug]
    except KeyError as exc:
        raise ToolError(f"Unknown tool: {slug}") from exc
    return tool_class(binary=binary)


def all_tools(binaries: dict[str, str] | None = None) -> list[SecurityTool]:
    binaries = binaries or {}
    return [tool_class(binary=binaries.get(slug)) for slug, tool_class in TOOL_CLASSES.items()]


__all__ = [
    "TOOL_CLASSES",
    "BuiltCommand",
    "FfufTool",
    "KatanaTool",
    "SecurityTool",
    "ToolError",
    "ToolStatus",
    "all_tools",
    "get_tool",
]
