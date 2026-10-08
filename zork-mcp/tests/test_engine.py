import pytest

from zork_mcp.engine import GameError, ZMachine


@pytest.fixture
def z():
    z = ZMachine()
    yield z
    z.stop()


def test_start_and_basic_commands(z):
    r = z.start("zork1")
    assert "West of House" in r.text
    assert "ZORK I" in r.text
    assert r.moves == 0 and r.score == 0
    assert "Score:" not in r.text  # status line stripped

    r = z.send("open mailbox")
    assert "leaflet" in r.text
    assert r.moves == 1

    r = z.send("take leaflet")
    assert "Taken" in r.text
    assert "leaflet" in z.send("inventory").text


def test_save_restore_roundtrip(z):
    z.start("zork1")
    z.send("open mailbox")
    z.save("pytest-slot")
    z.send("take leaflet")
    assert "leaflet" in z.send("inventory").text
    z.restore("pytest-slot")
    assert "empty-handed" in z.send("inventory").text
    z.save("pytest-slot")  # overwrite path
    assert "pytest-slot" in z.list_saves()


def test_save_cannot_escape_saves_dir(z):
    # Typing a path at the game's own save prompt stays confined to SAVES_DIR by -R.
    from zork_mcp.engine import SAVES_DIR

    z.start("zork1")
    z.send("save")
    z.send("../pytest-escape.qzl")
    assert not (SAVES_DIR.parent / "pytest-escape.qzl").exists()
    confined = SAVES_DIR / "pytest-escape.qzl"
    assert confined.exists()
    confined.unlink()


def test_history_is_recorded(z):
    z.start("zork1")
    z.send("open mailbox")
    turns = z.history.last(2)
    assert turns[0].command == "<start>"
    assert turns[1].command == "open mailbox" and "leaflet" in turns[1].reply


def test_stop_quits_cleanly(z):
    z.start("zork1")
    z.stop()
    assert not z.is_alive
    z.stop()  # idempotent


def test_restore_missing_save(z):
    z.start("zork1")
    with pytest.raises(GameError):
        z.restore("does-not-exist")


def test_send_without_game():
    with pytest.raises(GameError):
        ZMachine().send("look")


def test_unknown_game(z):
    with pytest.raises(GameError):
        z.start("nope")


@pytest.mark.parametrize("game,title", [("zork2", "ZORK II"), ("zork3", "ZORK III")])
def test_other_games_boot(z, game, title):
    assert title in z.start(game).text


def test_death_is_flagged(z):
    z.start("zork1")
    # Walk into the cellar with no light and keep going until the grue gets us.
    for cmd in ["s", "e", "open window", "w", "w", "move rug", "open trap door", "d"]:
        z.send(cmd)
    died = False
    for cmd in ["s", "s", "s", "n", "e", "w"]:
        if z.send(cmd).died:
            died = True
            break
    assert died
