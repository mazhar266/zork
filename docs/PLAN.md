# Plan: Zork MCP server for AI play

Goal: let an AI (Claude Code first) play Zork through an MCP server that wraps a
Z-machine interpreter. The server exposes the game as tools (`send_command`,
`look`, `save_game`, ...) and keeps the game process alive between calls.

This repo holds the 1977 MDL source, which can't run on Windows directly. The
plan therefore uses the Infocom Z-machine version (`zork1.z3`), which is the
same game ported to a format that has many modern interpreters. The engine is
isolated behind one class, so it can be swapped later for an ITS/MDL setup if
wanted.

## Current machine state (checked 2026-10-08)

| Tool | Status |
|---|---|
| Python 3.10.11 | installed (`C:\Users\mazha\AppData\Local\Programs\Python\Python310`) |
| uv | installed |
| Node 26 / npm | installed |
| git | installed |
| WSL | installed (`wsl.exe` present; distro not yet checked) |
| winget | installed |
| scoop | installed (`C:\Users\mazha\scoop`), but not on this session's PATH until the shell restarts |
| choco | installed (`C:\ProgramData\chocolatey`), same PATH caveat |
| WSL | Ubuntu distro installed (WSL2, currently stopped); `apt` offers `frotz` 2.55 |
| dotnet | installed (`C:\Program Files\dotnet`), enough to run ZILF |
| frotz / dfrotz | not installed yet |
| gcc / make | missing (only needed for Route B) |

Python 3.10 is the minimum for the official `mcp` SDK, so no upgrade is needed.

### What scoop and choco give us

- `scoop search frotz`: no match in the default bucket. Scoop has no dfrotz.
- `choco search frotz`: only `windows-frotz` 1.29.0. That is the GUI interpreter,
  not the headless `dfrotz` we need, so it's useful for manually playing and
  comparing output but not for the server.
- So neither package manager supplies `dfrotz`. Use WSL (Route A). Scoop/choco
  remain useful for tooling, e.g. `scoop install msys2` or `scoop install gcc`
  if Route B is ever needed.

## Proposed layout

```
zork/
  docs/PLAN.md            this file
  zork-mcp/
    pyproject.toml        uv project, deps: mcp[cli]
    src/zork_mcp/
      engine.py           ZMachine class: start/stop dfrotz, send, read, save/restore
      server.py           FastMCP server exposing the tools
      transcript.py       command/response history ring buffer
    games/                story files (gitignored, except a README on where to get them)
    saves/                save files written by the game (gitignored)
    tests/
      test_engine.py      drives dfrotz directly, no MCP
      test_server.py      drives the tools through the MCP client in-process
  .mcp.json               project-scoped MCP config for Claude Code
  CLAUDE.md               how Claude should play (short commands, save often, ...)
```

## Phase 1: Install a Z-machine runner

The MCP server needs a headless interpreter that talks over stdin/stdout.
`dfrotz` (the "dumb" build of Frotz) is the standard choice. There is no
official Windows binary, so there are two routes. Pick A unless WSL is broken.

### Route A (recommended): dfrotz inside WSL, called from Windows

1. Ubuntu is already installed (`wsl -l -v` shows it as the default, WSL2).
   Nothing to install at the WSL level.
2. Inside WSL: `sudo apt update && sudo apt install -y frotz`. The Debian/Ubuntu
   package ships both `frotz` and `dfrotz` (apt reports candidate 2.55). This
   needs a sudo password, so run it yourself in a terminal.
3. Verify from PowerShell: `wsl -e dfrotz -v`.
4. The Python server runs on Windows and spawns `wsl -e dfrotz -p -m -q -S 0 /mnt/c/.../zork1.z3`.
   Windows stdin/stdout pipes pass through `wsl.exe` cleanly, so the server code
   is the same as on Linux; only the executable path differs.

Flags used:
- `-p` plain ASCII output
- `-m` turn off `[MORE]` prompts, so output never blocks on a keypress
- `-q` quiet, no startup banner
- `-S 0` no status line, so room name and score don't pollute every reply
- `-R <dir>` optional: restrict file access (saves) to one directory

### Route B (fallback): native Windows build

- Build Frotz's dumb target with MSYS2 (`pacman -S mingw-w64-ucrt-x86_64-toolchain make`
  then `make dumb` in the Frotz source tree). Yields `dfrotz.exe`.
- Or use `bocfel` from the Gargoyle project, which also has a plain-terminal mode.
- Only worth doing if WSL is not available on the machine that will run the server.

### Deliverable
`dfrotz` runs and prints the Zork opening text when given a story file. Record
the exact command line in `zork-mcp/README.md`.

## Phase 2: Get and run the game

1. Obtain `zork1.z3` legally. Options, in order of ease:
   - Copy from an owned *Zork Anthology* (GOG/Steam). The files are named
     `ZORK1.DAT` etc. and are plain Z-machine v3 files; rename to `.z3`.
   - Compile from source: Microsoft/Activision released the Infocom ZIL source
     for Zork I-III on GitHub (`historicalsource/zork1`). Compile with ZILF
     (`zilf zork1.zil` then `zapf zork1.zap`), which needs the .NET runtime.
     Verify the repo and license are still as expected before relying on it.
   - Zork II and III can be added later the same way; the server should take the
     game as a parameter.
2. Put the file in `zork-mcp/games/`. Add `games/*.z?` and `saves/` to `.gitignore`.
3. Smoke test by hand:
   ```
   wsl -e dfrotz -p -m -q -S 0 /mnt/c/Users/mazha/Projects/zork/zork-mcp/games/zork1.z3
   ```
   Type `open mailbox`, `read leaflet`, `save` (answer the filename prompt),
   `quit`, `y`. Note exactly what the prompts look like; the engine class must
   recognise them.

### Deliverable
A documented, repeatable way to launch the game and the observed prompt
strings (`>`, `Please enter a file name`, `Are you sure you want to quit?`).

## Phase 3: Build the MCP server

### 3.1 Project setup
```
cd zork-mcp
uv init --package zork-mcp
uv add "mcp[cli]"
uv add --dev pytest pytest-asyncio
```

### 3.2 Engine (`engine.py`)
Responsibilities, all synchronous and engine-agnostic at the interface:
- `start(game_path)`: spawn the interpreter with `subprocess.Popen`, pipes for
  stdin/stdout, `text=True`, line buffering off. Return the opening text.
- `send(command) -> str`: write `command + "\n"`, then read until the game is
  waiting for input. dfrotz prints no end marker, so use a reader thread that
  pushes bytes into a queue and a read loop that stops when the buffer ends with
  `>` (or a known file-name prompt) and no new bytes arrive for ~150 ms.
  Strip the echoed prompt from the returned text.
- `save(name)` / `restore(name)`: send `save`, wait for the filename prompt,
  send `saves/<name>.qzl`, handle the "Overwrite existing file?" question.
- `stop()`: send `quit`, `y`, then terminate the process if still alive.
- Death detection: Zork prints `****  You have died  ****` and then asks
  whether to restart. Surface this as a flag in the response rather than
  answering automatically.
- Expose `is_alive`, `moves`, `score` parsed from an explicit `score` command,
  not from the status line (which is disabled).

### 3.3 Tools (`server.py`, FastMCP)

| Tool | Args | Returns |
|---|---|---|
| `start_game` | `game: str = "zork1"` | opening text; restarts if already running |
| `send_command` | `text: str` | game reply, plus `died: bool` |
| `look` | | reply to `look` |
| `inventory` | | reply to `inventory` |
| `get_score` | | `{score, moves}` parsed from `score` |
| `save_game` | `name: str` | confirmation |
| `load_game` | `name: str` | reply after restore |
| `list_saves` | | names in `saves/` |
| `get_history` | `n: int = 20` | last n `(command, reply)` pairs |
| `stop_game` | | confirmation |

Also expose a resource `zork://transcript` with the full transcript, and a
prompt `play-zork` that explains the parser's limits (two-word commands,
`examine`, `take all`, compass directions, `again`, save before risky moves).

Tool descriptions must carry the parser guidance, since that's what the model
reads when deciding what to type.

### 3.4 Robustness
- One game per server process; a lock around `send` so concurrent calls can't
  interleave.
- Time out reads after 5 s and return whatever arrived, with a `timed_out` flag.
- If the interpreter dies, `send_command` returns an error that tells the model
  to call `start_game`.
- Cap each reply at ~8 KB; Zork never prints more, so anything bigger means a
  parsing bug.

### 3.5 Tests
- `test_engine.py`: start game, assert opening text contains "West of House",
  send `open mailbox`, assert "leaflet", save and restore round trip, quit.
- `test_server.py`: use `mcp` client in-process over stdio, call `start_game`
  and `send_command`, assert the same strings.
- Run with `uv run pytest`. Requires Phase 1 and 2 done.

### 3.6 Manual check
`uv run mcp dev src/zork_mcp/server.py` opens the MCP Inspector in a browser;
call the tools by hand and watch the output.

## Phase 4: Integrate with Claude Code

1. Add `.mcp.json` at the repo root so the server is project-scoped and
   checked in:
   ```json
   {
     "mcpServers": {
       "zork": {
         "command": "uv",
         "args": ["--directory", "zork-mcp", "run", "zork-mcp"],
         "env": { "ZORK_GAMES_DIR": "zork-mcp/games" }
       }
     }
   }
   ```
   `zork-mcp` must be declared as a script entry point in `pyproject.toml`.
   Alternative for a user-wide install: `claude mcp add zork -- uv --directory <abs path> run zork-mcp`.
2. Approve the server when Claude Code prompts for project MCP servers, then
   confirm with `/mcp` in an interactive terminal that `zork` is connected and
   lists its tools.
3. Write `CLAUDE.md` with play guidance: start with `start_game`, call
   `save_game` every ~10 moves and before entering dark areas, read
   `get_history` after context compaction, don't repeat failed commands, map
   rooms in a scratch note.
4. Add a `/play-zork` skill (`.claude/skills/play-zork/SKILL.md`) that loads
   the strategy and a turn loop: observe, decide, act, record. Optional but
   makes "play Zork" a one-word request.
5. Try it: `claude` in the repo, say "play Zork for 30 moves and tell me your
   score". Watch for tool-call failures and reply truncation.
6. Optional: the same `.mcp.json` shape works for Claude Desktop
   (`claude_desktop_config.json`), so a non-Code user can play too.

## Phase 5: Later options

- Swap the engine for the 1977 MDL version: run ITS under SIMH, drive the
  MDL REPL over a telnet socket instead of a subprocess. The `ZMachine`
  interface stays the same.
- Multiple games in one server (Zork II, III, other Infocom titles).
- A spectator mode: write the transcript to a file or a small web page so a
  human can watch the AI play live.
- Benchmark harness: run N games, log score and moves, compare models.

## Order of work and checkpoints

1. Phase 1 â€” `wsl -e dfrotz -v` prints a version. (~30 min, more if WSL needs installing)
2. Phase 2 â€” opening text appears from a one-line command. (~30 min plus getting the story file)
3. Phase 3 â€” `uv run pytest` green, Inspector shows the tools. (~half a day)
4. Phase 4 â€” Claude Code plays 30 moves without a tool error. (~1 hour)

Phases 1 and 2 are blocking; Phase 3 can be written with a stub engine before
they finish, with the real interpreter plugged in once it's available.

## Status log

### 2026-10-08: Phases 1 and 2 done
- `dfrotz` 2.55 installed in WSL Ubuntu at `/usr/games/dfrotz`. That directory is
  **not on PATH** for `wsl -e`, so always call the full path.
- The `historicalsource/zork1|zork2|zork3` repos (MIT license, Microsoft 2025) already ship
  compiled story files in `COMPILED/`. **ZILF is not needed.** Cloned into
  `zork-mcp/vendor/` (gitignored) and copied to `zork-mcp/games/zork{1,2,3}.z3`.
- Working launch command:
  `wsl -d Ubuntu -e /usr/games/dfrotz -p -m -q -S 0 /mnt/c/Users/mazha/Projects/zork/zork-mcp/games/zork1.z3`
- Findings for the engine in Phase 3:
  - Piping from PowerShell prepended a stray character (`?open`). The server must write raw
    `\n`-terminated bytes with no BOM.
  - `-S 0` does **not** hide the status line. Each reply starts with a line like
    ` West of House     Score: 0     Moves: 1`. Strip it and parse score and moves from it,
    which makes a separate `score` command unnecessary.
  - The prompt is `>` with no trailing newline. Quit asks `Do you wish to leave the game? (Y is affirmative):`.
  - Still to observe: the save/restore filename prompts and the death/restart prompt.
- Zork 4 is not an Infocom title in the open-sourced set. Beyond Zork and Zork Zero are separate repos
  if wanted later.

### 2026-10-08: Phase 3 done, Phase 4 files written
- `zork-mcp/src/zork_mcp/engine.py` and `server.py` implemented; `uv run pytest` passes 9 tests
  (boot all 3 games, save/restore incl. overwrite, death detection, full MCP round trip over stdio).
- The installed `mcp` is **2.x**: `FastMCP` is now `MCPServer` (`mcp.server.mcpserver`).
- Prompts observed: `Please enter a filename [...]: `, `Overwrite existing file? ` (engine answers `y`),
  restore of a bad file prints `Failed.`.
- Added `.mcp.json` (project scope) and `CLAUDE.md`. Remaining: restart Claude Code in this folder,
  approve the `zork` server, confirm with `/mcp`, and run the 30-move trial.
