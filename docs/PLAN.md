# Plan: Zork MCP server for AI play

Goal: let an AI (Claude Code first) play Zork through an MCP server that wraps a
Z-machine interpreter. The server exposes the game as tools (`send_command`,
`look`, `save_game`, ...) and keeps the game process alive between calls.

This repo holds the 1977 MDL source, which can't run on Windows directly. The
plan therefore uses the Infocom Z-machine versions (`zork1.z3` etc.), the same
game ported to a format with many modern interpreters. The engine sits behind
one class, so it can be swapped later for an ITS/MDL setup.

## Status

| Phase | State | Checkpoint |
|---|---|---|
| 1. Z-machine runner | **done** | `wsl -d Ubuntu -e /usr/games/dfrotz -v` prints Frotz 2.55 |
| 2. Story files and game run | **done** | Zork I, II, III boot from the command line |
| 3. MCP server | **done** | `uv run pytest` passes 14 tests, incl. an MCP round trip over stdio |
| 4. Claude Code integration | files written, live trial pending | Claude Code plays 30 moves without a tool error |
| 5. Later options | not started | |

Still open in Phase 3: the manual check in the MCP Inspector (3.6). It downloads
the inspector through `npx` on first use, so it hasn't been run yet.

## Machine state (checked 2026-10-08)

| Tool | Status |
|---|---|
| Python 3.10.11 | installed; the minimum for the `mcp` SDK |
| uv | installed |
| Node 26 / npm | installed (needed only for the MCP Inspector) |
| git | installed |
| WSL | Ubuntu distro, WSL2 |
| dfrotz | Frotz 2.55 at `/usr/games/dfrotz` in WSL |
| dotnet | installed (would run ZILF; not needed, see Phase 2) |
| scoop, choco | installed, but neither offers `dfrotz` (choco's `windows-frotz` is the GUI build) |
| gcc / make | missing (only needed for the Route B native build) |

## Layout (as built)

```
zork/
  docs/PLAN.md              this file
  .mcp.json                 project-scoped MCP config for Claude Code
  CLAUDE.md                 play and dev guidance for Claude
  zork/                     the 1977 MDL source archive (untouched)
  zork-mcp/
    README.md               setup, launch command, tools, config
    pyproject.toml          uv project; deps: mcp[cli] 2.x; script: zork-mcp
    src/zork_mcp/
      engine.py             ZMachine: start/stop dfrotz, send, read, save/restore
      server.py             MCPServer exposing the tools
      transcript.py         bounded command/reply history
    games/zork{1,2,3}.z3    story files (committed; MIT-licensed builds)
    saves/                  save files (gitignored; dfrotz -R sandbox)
    vendor/                 cloned source repos (gitignored)
    tests/
      test_engine.py        drives dfrotz directly
      test_server.py        drives the tools through an MCP client over stdio
      test_transcript.py    history buffer
```

## Phase 1: Install a Z-machine runner (done)

The server needs a headless interpreter that talks over stdin/stdout. `dfrotz`
(the "dumb" build of Frotz) is the standard choice. There's no official
Windows binary, so it runs in WSL.

### Route A (used): dfrotz in WSL, called from Windows

1. Ubuntu was already installed under WSL2.
2. `sudo apt install -y frotz` in Ubuntu installs `frotz` and `dfrotz` 2.55.
3. `/usr/games` is **not on PATH** for `wsl -e`, so call `/usr/games/dfrotz`.
4. The Python server runs on Windows and spawns
   `wsl -d Ubuntu -e /usr/games/dfrotz ...`. Pipes pass through `wsl.exe` fine.

Flags:
- `-p` plain ASCII output
- `-m` no `[MORE]` prompts, so output never waits for a keypress
- `-q` no startup banner
- `-S 0` meant to hide the status line, but dfrotz 2.55 still prints it (see findings)
- `-R <saves dir>` confine save/restore to one directory

### Route B (not needed): native Windows build

Build Frotz's dumb target with MSYS2 (`scoop install msys2`, then the mingw
toolchain and `make dumb`), or use `bocfel`. Only if WSL isn't available.

## Phase 2: Story files and running the game (done)

- Microsoft's MIT-licensed releases `github.com/historicalsource/zork1`,
  `zork2` and `zork3` already ship compiled `.z3` files in `COMPILED/`, so
  **ZILF isn't needed**. The repos are cloned to `zork-mcp/vendor/`
  (gitignored), and the `.z3` files are copied to `zork-mcp/games/`.
- Unlike the original plan, the `.z3` files **are committed**. They're small
  (about 260 KB in total) and MIT-licensed.
- There is no Infocom "Zork 4". *Beyond Zork* (Z-machine v5) and *Zork Zero*
  have their own repos if wanted later; the engine would need to accept `.z5`/`.z6`.
- Launch command (also in `zork-mcp/README.md`):
  ```
  wsl -d Ubuntu -e /usr/games/dfrotz -p -m -q -S 0 -R /mnt/c/Users/mazha/Projects/zork/zork-mcp/saves /mnt/c/Users/mazha/Projects/zork/zork-mcp/games/zork1.z3
  ```

### Observed interpreter behaviour

| Situation | Output |
|---|---|
| Waiting for a command | `>` with no trailing newline |
| Each turn | status line first: ` West of House      Score: 0     Moves: 1` |
| `save` / `restore` | `Please enter a filename [default.qzl]: ` |
| Save over an existing file | `Overwrite existing file? ` |
| Restore failure | `Failed.` |
| `quit` | `Do you wish to leave the game? (Y is affirmative): ` |
| Death | `****  You have died  ****` |
| First output after launch | takes over 1.5 s (WSL start-up) |
| `-R` with a path typed | path reduced to basename and written inside the `-R` dir |

Piping commands from PowerShell put a stray character before the first one
(`?open`), so the server writes raw `\n`-terminated bytes itself.

## Phase 3: MCP server (done)

### 3.1 Project setup
```
cd zork-mcp
uv init --package --name zork-mcp .
uv add "mcp[cli]"
uv add --dev pytest anyio
```
The installed SDK is **mcp 2.x**: `FastMCP` was renamed to `MCPServer`
(`from mcp.server.mcpserver import MCPServer`). The decorators (`tool`,
`resource`, `prompt`) and `run()` are unchanged.

### 3.2 Engine (`engine.py`)
- `start(game)`: spawns dfrotz with pipes. A reader thread pushes raw chunks into a
  queue. The first read waits up to 20 s for WSL to start.
- `send(command)`: writes `command\n` and reads until the buffer ends in a
  prompt (`>`, `]: `, `? `, `): `) and output has been quiet for 250 ms. If
  output stops for 2 s without a recognised prompt, it returns what it has. A
  hard limit of 8 s sets `timed_out`.
- The status line is stripped from the text and parsed into `room`, `score`
  and `moves`. That replaces the planned `score`-command parsing.
- `save(name)` / `restore(name)`: names are sanitised to `[A-Za-z0-9_-]` and passed as
  bare filenames, which `-R` resolves inside `saves/`. Overwrite prompts are
  answered `y`. Restore checks the file exists first and raises on `Failed.`.
- `stop()`: sends `quit` and `y` and waits 3 s, then kills the process. It's idempotent.
- Death sets a `died` flag. The game's own restart/restore/quit question is
  left to the model.
- History is a `Transcript` (bounded deque, last 1000 turns) in `transcript.py`.

### 3.3 Tools (`server.py`)

| Tool | Args | Returns |
|---|---|---|
| `start_game` | `game_name="zork1"` | opening text; restarts if a game is running |
| `send_command` | `text` | reply plus `[room, score, moves]`, death / timeout / ended flags |
| `look` | | reply to `look` |
| `inventory` | | reply to `inventory` |
| `get_score` | | reply to `score` (score and rank) |
| `get_status` | | last known room, score, moves; no command sent |
| `save_game` | `name` | confirmation |
| `load_game` | `name` | reply after restore |
| `list_saves` | | names in `saves/` |
| `get_history` | `n=20` (1–200) | last n commands with replies |
| `list_games` | | story files available |
| `stop_game` | | confirmation |

Also the resource `zork://transcript` (full transcript), and the prompt
`play_zork(goal)` (strategy briefing). The server `instructions` and tool
descriptions carry the parser guidance: short verb-noun commands, directions,
and rephrasing when a word is unknown.

### 3.4 Robustness
- One game per server process. An `RLock` serialises every command, including
  multi-step save/restore.
- If the interpreter has exited, every command returns
  `Error: No game is running. Call start_game first.`
- Replies are capped at 8 KB.
- Tool errors (`GameError`) are returned as `Error: ...` text, not as
  exceptions, so the model can read them and recover.
- Saves are sandboxed by `-R`. Even if the model types `save` and then
  `/tmp/x` or `../x` through `send_command`, the file lands in `saves/`.

### 3.5 Tests (`uv run pytest`: 14 passed)
- `test_engine.py`:
  - boot Zork I and check the status line is stripped;
  - basic commands;
  - save/restore round trip, including overwrite;
  - the `-R` sandbox;
  - history recording;
  - clean, idempotent stop;
  - errors for a missing save, no game running, and an unknown game;
  - Zork II and III boot;
  - death is flagged after walking into the dark cellar.
- `test_server.py`: an MCP client over stdio lists the tools, starts a game,
  sends a command, reads the history, and gets an `Error:` from a bad load.
- `test_transcript.py`: the buffer is bounded and renders correctly.

### 3.6 Manual check (pending)
`uv run mcp dev src/zork_mcp/server.py` starts the MCP Inspector. It fetches
`@modelcontextprotocol/inspector` through `npx` the first time. Call
`start_game` and `send_command` by hand to check the output looks right to a human.

## Phase 4: Integrate with Claude Code

Done:
1. `.mcp.json` at the repo root:
   ```json
   { "mcpServers": { "zork": { "command": "uv", "args": ["--directory", "zork-mcp", "run", "zork-mcp"] } } }
   ```
   `zork-mcp = "zork_mcp.server:main"` is the script entry point in `pyproject.toml`.
   For a user-wide install instead:
   `claude mcp add zork -- uv --directory C:\Users\mazha\Projects\zork\zork-mcp run zork-mcp`.
2. `CLAUDE.md` with play guidance (start, save often, `get_history` after a
   reset, keep a map, manage the lamp) and dev notes.

To do:
3. Open a new Claude Code session in the repo and approve the project MCP server.
   Then confirm with `/mcp` in an interactive terminal that `zork` is connected
   with its 13 tools.
4. Optional: a `/play-zork` skill (`.claude/skills/play-zork/SKILL.md`) with a
   turn loop (observe, decide, act, record).
5. Trial: "play Zork for 30 moves and tell me your score". Watch for tool
   errors, timeouts and truncated replies.
6. Optional: the same server entry works in Claude Desktop's `claude_desktop_config.json`.

## Phase 5: Later options

- Swap the engine for the 1977 MDL version: run ITS under SIMH and drive the
  MDL REPL over a telnet socket. The `ZMachine` interface stays the same.
- More games: *Beyond Zork* and *Zork Zero* (`.z5` and `.z6`), or other Infocom titles.
- Spectator mode: stream the transcript to a small web page.
- Benchmark harness: run N games, log score and moves, compare models.
