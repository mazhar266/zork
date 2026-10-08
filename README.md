# Zork source code, 1977
This repository contains the source code for a 1977 version of [Zork](https://en.wikipedia.org/wiki/Zork), an interactive fiction game created at MIT by Tim Anderson, Marc Blank, Bruce Daniels, and Dave Lebling. The files are a part of the [Massachusetts Institute of Technology, Tapes of Tech Square (ToTS) collection](https://archivesspace.mit.edu/repositories/2/resources/1265) at the MIT Libraries Department of Distinctive Collections (DDC).
## File organization and details
### [zork](../master/zork)
The files within this directory are the Zork specific files from the ```9005196.tap``` tape image file within the ```/tots/recovered/vol2``` directory of the [ToTS collection](https://archivesspace.mit.edu/repositories/2/resources/1265). Most files are written in the MDL programming language and were originally created on a PDP-10 timeshare computer running the ITS operating system.

The files were extracted from the tape image using the [itstar program](https://github.com/PDP-10/itstar). The filenames have been adapted to Unix conventions, as per the itstar translation. The original filename syntax would be formatted like, ```LCF; ACT1 37```, for example. All files have been placed into this artificial zork directory for organizational purposes.

The [```lcf```](../master/zork/lcf) and [```madman```](../master/zork/madman) directories contain the source code for the game.

The [```act2.27```](../master/zork/act2.27) and [```dung.56```](../master/zork/dung.56) files outside of the two main directories, are the decrypted versions of [```act2z.27```](../master/zork/lcf/act2z.27) and [```dungz.56```](../master/zork/lcf/dungz.56). The decrypted versions were created recently and added to this directory by DDC digital archivist, Joe Carrano, for researcher ease of access.  

Files with extensions ```.nbin``` and ```.save``` are binary compiled files.

There was a ```zork.log``` file within the [```madman```](../master/zork/madman) directory that detailed who played Zork at the time of creation. DDC excluded this file from public release to protect the privacy of those named.

### [codemeta.json](../master/codemeta.json)
This file is metadata about the Zork files, using the [CodeMeta Project](https://codemeta.github.io/) schema.
### [LICENSE.md](../main/LICENSE.md)
This file describes the details about the rights to these files. See [Rights](#rights) for additional information.
### [README.md](../master/README.md)
This file is the readme detailing the content and context for this repository.
### [tree.txt](../master/tree.txt)
A file tree listing the files in the [```zork```](../master/zork) directory showing the original file timestamps as extracted from the tape image.

## Playing Zork with an AI: the Zork MCP server
The [`zork-mcp`](zork-mcp) folder adds an [MCP](https://modelcontextprotocol.io) server that lets an AI assistant such as Claude Code play Infocom's Zork I, II and III. It does not run the 1977 MDL source above. It runs the compiled Z-machine story files (`zork-mcp/games/zork{1,2,3}.z3`) from Microsoft's MIT-licensed [historicalsource](https://github.com/historicalsource/zork1) releases, using the `dfrotz` interpreter in WSL.

### 1. Install the prerequisites (Windows)
- **WSL with Ubuntu:** `wsl --install -d Ubuntu`, if you don't already have it.
- **dfrotz:** inside Ubuntu, run the following. It installs `/usr/games/dfrotz`.
  ```bash
  sudo apt update && sudo apt install -y frotz
  ```
- **uv** (Python 3.10+): see https://docs.astral.sh/uv/.

Check that the game runs:
```bash
wsl -d Ubuntu -e /usr/games/dfrotz -v
```

### 2. Install and test the server
```bash
cd zork-mcp
uv sync
uv run pytest
```
All tests should pass. They boot each game, save and restore, detect death, and make a full MCP round trip.

### 3. Use it from Claude Code
The repository root has a project-scoped [`.mcp.json`](.mcp.json):
```json
{ "mcpServers": { "zork": { "command": "uv", "args": ["--directory", "zork-mcp", "run", "zork-mcp"] } } }
```
1. Start Claude Code in the repository root and approve the `zork` server when asked.
2. Run `/mcp` to check that `zork` is connected.
3. Ask, for example: *"Start Zork I and play 30 moves, then tell me your score."*

To make the server available in every project instead, use an absolute path:
```bash
claude mcp add zork -- uv --directory C:\path\to\zork\zork-mcp run zork-mcp
```

### 4. Use it from Claude Desktop or another MCP client
Add the same server to `claude_desktop_config.json` (or your client's config), using an absolute path:
```json
{
  "mcpServers": {
    "zork": {
      "command": "uv",
      "args": ["--directory", "C:\\path\\to\\zork\\zork-mcp", "run", "zork-mcp"]
    }
  }
}
```

### 5. Try the tools by hand (optional)
```bash
cd zork-mcp
uv run mcp dev src/zork_mcp/server.py
```
This opens the MCP Inspector in a browser. The first run downloads it through `npx`.

### Tools
| Tool | Purpose |
|---|---|
| `start_game(game_name="zork1")` | Start or restart `zork1`, `zork2` or `zork3` and return the opening text |
| `send_command(text)` | Send one command (`open mailbox`, `n`, `take lamp`) and return the reply with room, score and moves |
| `look`, `inventory`, `get_score` | Shortcuts for those commands |
| `get_status` | Last known room, score and moves, without using a move |
| `save_game(name)`, `load_game(name)`, `list_saves` | Save files are kept in `zork-mcp/saves/` |
| `get_history(n=20)` | The last n commands and replies |
| `list_games`, `stop_game` | Housekeeping |

There is also a `zork://transcript` resource and a `play_zork` prompt.

### Configuration
Optional environment variables: `ZORK_GAMES_DIR`, `ZORK_SAVES_DIR`, `ZORK_DFROTZ` (default `/usr/games/dfrotz`) and `ZORK_WSL_DISTRO` (default `Ubuntu`). Saves are confined to the saves folder by dfrotz's `-R` option.

More details are in [`zork-mcp/README.md`](zork-mcp/README.md). Plans are in [`docs/PLAN.md`](docs/PLAN.md) (the MCP server) and [`docs/WEBSITE_PLAN.md`](docs/WEBSITE_PLAN.md) (a website where an AI plays nonstop).

## Preferred Citation
[filename], Zork source code, 1977, Massachusetts Institute of Technology, Tapes of Tech Square (ToTS) collection, MC-0741. Massachusetts Institute of Technology, Department of Distinctive Collections, Cambridge, Massachusetts. [swh:1:dir:ab9e2babe84cfc909c64d66291b96bb6b9d8ca15](https://archive.softwareheritage.org/swh:1:dir:ab9e2babe84cfc909c64d66291b96bb6b9d8ca15)
## Rights
To the extent that MIT holds rights in these files, they are released under the terms of the [MIT No Attribution License](https://opensource.org/licenses/MIT-0). See the ```LICENSE.md``` file for more information. Any questions about permissions should be directed to [permissions-lib@mit.edu](mailto:permissions-lib@mit.edu)
## Acknowledgements
Thanks to [Lars Brinkhoff](https://github.com/larsbrinkhoff) for help with identifying these files and with extracting them using the itstar program mentioned above.
