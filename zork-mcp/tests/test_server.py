import sys

import anyio
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _text(result) -> str:
    return "".join(c.text for c in result.content if getattr(c, "text", None))


@pytest.mark.anyio
async def test_play_over_mcp():
    params = StdioServerParameters(command=sys.executable, args=["-m", "zork_mcp.server"])
    with anyio.fail_after(90):
        async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            tools = {t.name for t in (await s.list_tools()).tools}
            assert {"start_game", "send_command", "save_game", "load_game", "get_history"} <= tools

            opening = _text(await s.call_tool("start_game", {}))
            assert "West of House" in opening

            reply = _text(await s.call_tool("send_command", {"text": "open mailbox"}))
            assert "leaflet" in reply and "moves=1" in reply

            hist = _text(await s.call_tool("get_history", {"n": 1}))
            assert "> open mailbox" in hist

            err = _text(await s.call_tool("load_game", {"name": "nope"}))
            assert err.startswith("Error:")

            await s.call_tool("stop_game", {})
