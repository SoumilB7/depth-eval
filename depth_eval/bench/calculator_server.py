"""The two calculators as a stdio MCP server — the arena's only tools.

A thin transport over calculator.py: the same names, descriptions and
input schemas the API solver sends, the same arithmetic, the same error
text (is_error on a CalculatorError). Nothing else is exposed.

    python -m depth_eval.bench.calculator_server
"""

import anyio
import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from .calculator import TOOLS, CalculatorError

server = Server("calculators")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [types.Tool(name=t.name, description=t.description, inputSchema=t.input_schema)
            for t in TOOLS.values()]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> types.CallToolResult:
    try:
        if name not in TOOLS:
            raise CalculatorError(f"unknown tool {name!r}")
        return types.CallToolResult(content=[types.TextContent(type="text", text=TOOLS[name].run(arguments))])
    except CalculatorError as e:
        return types.CallToolResult(content=[types.TextContent(type="text", text=f"Error: {e}")],
                                    isError=True)


async def main() -> None:
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    anyio.run(main)
