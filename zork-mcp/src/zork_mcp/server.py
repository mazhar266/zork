"""MCP server that lets an AI play Infocom's Zork through a Z-machine interpreter."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from .engine import GAMES_DIR, GameError, Reply, ZMachine

mcp = MCPServer(
    "zork",
    instructions=(
        "Play Zork, a text adventure. Call start_game first, then send_command repeatedly. "
        "Commands are short imperative phrases the game parser understands: verb + noun, "
        "e.g. 'open mailbox', 'take lamp', 'go north' or just 'n', 'put coin in slot', "
        "'attack troll with sword'. Compass directions: n s e w ne nw se sw u d. "
        "Other useful verbs: look, inventory, examine X, read X, turn on lamp, unlock X with Y. "
        "Save with save_game before anything dangerous."
    ),
)

game = ZMachine()


def _fmt(reply: Reply) -> str:
    parts = [reply.text or "(no output)"]
    meta = []
    if reply.room:
        meta.append(f"room={reply.room}")
    if reply.score is not None:
        meta.append(f"score={reply.score}")
    if reply.moves is not None:
        meta.append(f"moves={reply.moves}")
    if reply.died:
        meta.append("YOU DIED - the game may be asking to restart/restore/quit; use load_game or start_game")
    if reply.timed_out:
        meta.append("timed_out=true (reply may be incomplete)")
    if reply.finished:
        meta.append("game_ended=true (call start_game to play again)")
    if meta:
        parts.append("[" + ", ".join(meta) + "]")
    return "\n\n".join(parts)


def _run(fn, *args):
    try:
        return fn(*args)
    except GameError as e:
        return f"Error: {e}"


@mcp.tool()
def start_game(game_name: str = "zork1") -> str:
    """Start (or restart) a game and return the opening text.

    game_name: one of the story files in the games folder, e.g. 'zork1', 'zork2', 'zork3'.
    Any game in progress is discarded; use save_game first if you want to keep it.
    """
    return _run(lambda: _fmt(game.start(game_name)))


@mcp.tool()
def send_command(text: str) -> str:
    """Send one command to the game and return its reply.

    Use short verb-noun phrases ('take lamp', 'open door', 'go north' or 'n').
    One action per call. The reply ends with [room, score, moves] when known.
    If the game says it doesn't know a word, rephrase with simpler words.
    """
    return _run(lambda: _fmt(game.send(text)))


@mcp.tool()
def look() -> str:
    """Describe the current room again (the 'look' command). Costs one move."""
    return _run(lambda: _fmt(game.send("look")))


@mcp.tool()
def inventory() -> str:
    """List what the player is carrying (the 'inventory' command)."""
    return _run(lambda: _fmt(game.send("inventory")))


@mcp.tool()
def get_status() -> str:
    """Return the last known room, score and move count without sending a command."""
    if not game.is_alive:
        return "No game is running. Call start_game."
    return f"game={game.game}, room={game.room}, score={game.score}, moves={game.moves}"


@mcp.tool()
def save_game(name: str) -> str:
    """Save the current game under a name (letters, digits, - and _). Overwrites an existing save."""
    return _run(lambda: f"Saved as {name!r}.\n{game.save(name)}")


@mcp.tool()
def load_game(name: str) -> str:
    """Restore a previously saved game by name. Use list_saves to see names."""
    return _run(lambda: _fmt(game.restore(name)))


@mcp.tool()
def list_saves() -> list[str]:
    """List the names of saved games."""
    return game.list_saves()


@mcp.tool()
def get_history(n: int = 20) -> str:
    """Return the last n commands with the game's replies, oldest first. Useful after losing context."""
    n = max(1, min(n, 200))
    if not game.history:
        return "No history yet."
    return "\n\n".join(f"> {cmd}\n{text}" for cmd, text in game.history[-n:])


@mcp.tool()
def list_games() -> list[str]:
    """List the story files available to start_game."""
    return sorted(p.stem for p in GAMES_DIR.glob("*.z*"))


@mcp.tool()
def stop_game() -> str:
    """Stop the running game and free the interpreter process."""
    game.stop()
    return "Game stopped."


@mcp.resource("zork://transcript")
def transcript() -> str:
    """The full transcript of the current game."""
    return "\n\n".join(f"> {cmd}\n{text}" for cmd, text in game.history) or "No game yet."


@mcp.prompt()
def play_zork(goal: str = "Explore and score as many points as you can.") -> str:
    """Strategy briefing for playing Zork."""
    return (
        f"You are playing Zork. Goal: {goal}\n\n"
        "Start with start_game. Then loop: read the reply, decide one action, send_command.\n"
        "- Keep a running map of rooms and exits in your notes.\n"
        "- The lamp is essential below ground; turn it on before the dark and don't waste battery.\n"
        "- save_game every ~10 moves and before fights or unknown places.\n"
        "- If a command fails, rephrase, don't repeat it. 'examine' things you can't use yet.\n"
        "- After a context reset, call get_history to catch up."
    )


def main() -> None:
    try:
        mcp.run()
    finally:
        game.stop()


if __name__ == "__main__":
    main()
