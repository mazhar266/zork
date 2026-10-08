"""Bounded command/reply history for a game session."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class Turn:
    command: str
    reply: str


class Transcript:
    def __init__(self, maxlen: int = 1000) -> None:
        self._turns: deque[Turn] = deque(maxlen=maxlen)

    def add(self, command: str, reply: str) -> None:
        self._turns.append(Turn(command, reply))

    def clear(self) -> None:
        self._turns.clear()

    def last(self, n: int) -> list[Turn]:
        if n <= 0:
            return []
        return list(self._turns)[-n:]

    def __len__(self) -> int:
        return len(self._turns)

    def render(self, n: int | None = None) -> str:
        turns = list(self._turns) if n is None else self.last(n)
        return "\n\n".join(f"> {t.command}\n{t.reply}" for t in turns)
