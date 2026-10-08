# Zork MCP

`zork-mcp/` is an MCP server that wraps Infocom's Zork I-III (Z-machine `.z3` files in
`zork-mcp/games/`) via `dfrotz` running in WSL. The `zork/` folder is the unrelated 1977 MDL
source archive. Plan and status: `docs/PLAN.md`.

## Playing (when the `zork` MCP server is connected)

- `start_game` first (`zork1` by default), then `send_command` one short verb-noun command at a time.
- `save_game` about every 10 moves and before fights or unknown areas; `load_game` after dying.
- After a context reset, call `get_history` to catch up before acting.
- Keep your own running map of rooms and exits. Don't repeat a failed command; rephrase or `examine`.
- Zork's lamp matters underground: turn it on before dark areas, and don't leave it on needlessly.

## Developing

- `cd zork-mcp && uv run pytest` (needs WSL Ubuntu with `/usr/games/dfrotz`).
- Server is mcp 2.x: `from mcp.server.mcpserver import MCPServer` (not FastMCP).
- Engine quirks are in `src/zork_mcp/engine.py`: status line is stripped and parsed, prompts end
  in `>`, `]: `, `? ` or `): `.
