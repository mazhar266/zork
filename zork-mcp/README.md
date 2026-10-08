# zork-mcp

An MCP server that lets an AI play Infocom's Zork I, II and III. It runs the
games in `dfrotz` (headless Frotz) inside WSL and exposes them as MCP tools.

## Requirements

- Windows with WSL and an Ubuntu distro
- `dfrotz` in WSL: `sudo apt install -y frotz` (installs `/usr/games/dfrotz`)
- [uv](https://docs.astral.sh/uv/) and Python 3.10+

## Running the game by hand

`/usr/games` is not on PATH for `wsl -e`, so use the full path:

```
wsl -d Ubuntu -e /usr/games/dfrotz -p -m -q -S 0 -R /mnt/c/Users/mazha/Projects/zork/zork-mcp/saves /mnt/c/Users/mazha/Projects/zork/zork-mcp/games/zork1.z3
```

| Flag | Meaning |
|---|---|
| `-p` | plain ASCII output |
| `-m` | no `[MORE]` prompts |
| `-q` | no startup banner |
| `-S 0` | intended to hide the status line; dfrotz 2.55 still prints it, the engine strips it |
| `-R <dir>` | confine save/restore files to `<dir>`; any path typed is reduced to its basename |

## Running the server

```
uv run zork-mcp            # stdio MCP server
uv run mcp dev src/zork_mcp/server.py   # MCP Inspector in a browser (downloads the inspector via npx)
uv run pytest              # tests; needs WSL + dfrotz
```

## Tools

| Tool | Purpose |
|---|---|
| `start_game(game_name="zork1")` | start or restart a game, return the opening text |
| `send_command(text)` | send one command, return the reply with `[room, score, moves]` |
| `look`, `inventory`, `get_score` | shortcuts for those commands |
| `get_status` | last known room/score/moves, no command sent |
| `save_game(name)`, `load_game(name)`, `list_saves` | save files in `saves/` |
| `get_history(n=20)` | last n commands and replies |
| `list_games`, `stop_game` | housekeeping |

Plus the resource `zork://transcript` and the prompt `play_zork`.

## Configuration

Environment variables, all optional:

| Variable | Default |
|---|---|
| `ZORK_GAMES_DIR` | `zork-mcp/games` |
| `ZORK_SAVES_DIR` | `zork-mcp/saves` |
| `ZORK_DFROTZ` | `/usr/games/dfrotz` |
| `ZORK_WSL_DISTRO` | `Ubuntu` |

## Story files

`games/zork{1,2,3}.z3` are the compiled builds shipped in Microsoft's
MIT-licensed source releases: `github.com/historicalsource/zork1`, `zork2`
and `zork3` (the `COMPILED/` folder of each).
