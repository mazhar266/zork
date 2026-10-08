"""Drives a Z-machine story file through dfrotz (the dumb Frotz build) in WSL.

dfrotz prints no end-of-output marker, so a reply is considered complete when the
buffer ends in a known prompt, or when output has been quiet for a short while.
"""

from __future__ import annotations

import os
import queue
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(os.environ.get("ZORK_ROOT", Path(__file__).resolve().parents[2]))
GAMES_DIR = Path(os.environ.get("ZORK_GAMES_DIR", ROOT / "games"))
SAVES_DIR = Path(os.environ.get("ZORK_SAVES_DIR", ROOT / "saves"))
DFROTZ = os.environ.get("ZORK_DFROTZ", "/usr/games/dfrotz")
WSL_DISTRO = os.environ.get("ZORK_WSL_DISTRO", "Ubuntu")

STATUS_RE = re.compile(r"^\s*(?P<room>.+?)\s{2,}Score:\s*(?P<score>-?\d+)\s+Moves:\s*(?P<moves>\d+)\s*$")
# The game is waiting for input after one of these.
PROMPT_END_RE = re.compile(r"(>|\]: |\? |\): )$")
DEATH_RE = re.compile(r"\*{4}\s+You have died\s+\*{4}")
MAX_REPLY = 8000


class GameError(RuntimeError):
    pass


@dataclass
class Reply:
    text: str
    room: str | None = None
    score: int | None = None
    moves: int | None = None
    died: bool = False
    timed_out: bool = False
    finished: bool = False  # the interpreter exited


@dataclass
class ZMachine:
    game: str = ""
    history: list[tuple[str, str]] = field(default_factory=list)
    room: str | None = None
    score: int | None = None
    moves: int | None = None
    _proc: subprocess.Popen | None = None
    _queue: "queue.Queue[bytes]" = field(default_factory=queue.Queue)
    _lock: threading.RLock = field(default_factory=threading.RLock)

    # ---- lifecycle -------------------------------------------------------

    @property
    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self, game: str = "zork1") -> Reply:
        with self._lock:
            self.stop()
            story = GAMES_DIR / f"{game}.z3"
            if not story.is_file():
                available = sorted(p.stem for p in GAMES_DIR.glob("*.z*"))
                raise GameError(f"Unknown game {game!r}. Available: {available}")
            SAVES_DIR.mkdir(parents=True, exist_ok=True)
            self.game = game
            self.history.clear()
            self.room = self.score = self.moves = None
            self._queue = queue.Queue()
            cmd = ["wsl", "-d", WSL_DISTRO, "-e", DFROTZ, "-p", "-m", "-q", "-S", "0", _wsl_path(story)]
            self._proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
            )
            threading.Thread(target=self._pump, args=(self._proc, self._queue), daemon=True).start()
            reply = self._read(first_timeout=20.0)
            self.history.append(("<start>", reply.text))
            return reply

    def stop(self) -> None:
        with self._lock:
            if self._proc is not None:
                if self._proc.poll() is None:
                    self._proc.kill()
                self._proc.wait()
                self._proc = None

    # ---- commands --------------------------------------------------------

    def send(self, command: str) -> Reply:
        with self._lock:
            reply = self._raw_send(command)
            self.history.append((command, reply.text))
            return reply

    def save(self, name: str) -> str:
        path = _wsl_path(SAVES_DIR / f"{_safe_name(name)}.qzl")
        with self._lock:
            out = self._raw_send("save")
            if "filename" not in out.text:
                raise GameError(f"Game did not ask for a filename. Reply: {out.text!r}")
            out = self._raw_send(path)
            if "Overwrite" in out.text:
                out = self._raw_send("y")
            self.history.append((f"<save {name}>", out.text))
            if "Ok." not in out.text:
                raise GameError(f"Save failed: {out.text!r}")
            return out.text

    def restore(self, name: str) -> Reply:
        file = SAVES_DIR / f"{_safe_name(name)}.qzl"
        if not file.is_file():
            raise GameError(f"No save named {name!r}. Saves: {self.list_saves()}")
        with self._lock:
            out = self._raw_send("restore")
            if "filename" not in out.text:
                raise GameError(f"Game did not ask for a filename. Reply: {out.text!r}")
            out = self._raw_send(_wsl_path(file))
            self.history.append((f"<restore {name}>", out.text))
            if "Failed" in out.text:
                raise GameError("Restore failed.")
            return out

    @staticmethod
    def list_saves() -> list[str]:
        return sorted(p.stem for p in SAVES_DIR.glob("*.qzl")) if SAVES_DIR.is_dir() else []

    # ---- internals -------------------------------------------------------

    def _raw_send(self, command: str) -> Reply:
        if not self.is_alive:
            raise GameError("No game is running. Call start_game first.")
        command = command.replace("\r", " ").replace("\n", " ").strip()
        assert self._proc and self._proc.stdin
        try:
            self._proc.stdin.write(command.encode("utf-8") + b"\n")
            self._proc.stdin.flush()
        except OSError as e:
            raise GameError(f"Game process is gone: {e}. Call start_game.") from e
        return self._read()

    @staticmethod
    def _pump(proc: subprocess.Popen, q: "queue.Queue[bytes]") -> None:
        assert proc.stdout
        for chunk in iter(lambda: proc.stdout.read1(4096), b""):
            q.put(chunk)
        q.put(b"")  # EOF marker

    def _read(self, first_timeout: float = 8.0, quiet: float = 0.25) -> Reply:
        buf = b""
        deadline = time.monotonic() + first_timeout
        last_data = None
        eof = False
        timed_out = False
        while True:
            now = time.monotonic()
            if now > deadline:
                timed_out = True
                break
            try:
                chunk = self._queue.get(timeout=0.05)
            except queue.Empty:
                text = buf.decode("utf-8", "replace")
                if last_data is not None and now - last_data > quiet and PROMPT_END_RE.search(text):
                    break
                if last_data is not None and now - last_data > 2.0:
                    break  # output stopped without a recognised prompt
                continue
            if chunk == b"":
                eof = True
                break
            buf += chunk
            last_data = time.monotonic()
            if len(buf) > MAX_REPLY * 4:
                break
        return self._parse(buf.decode("utf-8", "replace"), timed_out, eof)

    def _parse(self, raw: str, timed_out: bool, eof: bool) -> Reply:
        raw = raw.replace("\r\n", "\n")
        kept: list[str] = []
        for line in raw.split("\n"):
            m = STATUS_RE.match(line.lstrip(">").rstrip())
            if m:
                self.room, self.score, self.moves = m["room"], int(m["score"]), int(m["moves"])
                continue
            kept.append(line.lstrip(">") if line.startswith(">") and not line.startswith(">>") else line)
        text = "\n".join(kept).strip()
        text = re.sub(r"\n{3,}", "\n\n", text)
        if text.endswith(">"):
            text = text[:-1].rstrip()
        if len(text) > MAX_REPLY:
            text = text[:MAX_REPLY] + "\n[output truncated]"
        return Reply(
            text=text,
            room=self.room,
            score=self.score,
            moves=self.moves,
            died=bool(DEATH_RE.search(text)),
            timed_out=timed_out,
            finished=eof,
        )


def _safe_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "_", name.strip())
    if not cleaned:
        raise GameError("Save name must contain letters or digits.")
    return cleaned[:48]


def _wsl_path(path: Path) -> str:
    p = Path(path).resolve()
    drive = p.drive.rstrip(":").lower()
    rest = p.as_posix()[len(p.drive):]
    return f"/mnt/{drive}{rest}"
