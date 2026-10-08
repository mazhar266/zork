from zork_mcp.transcript import Transcript


def test_bounded_and_ordered():
    t = Transcript(maxlen=3)
    for i in range(5):
        t.add(f"c{i}", f"r{i}")
    assert len(t) == 3
    assert [x.command for x in t.last(10)] == ["c2", "c3", "c4"]
    assert [x.command for x in t.last(1)] == ["c4"]
    assert t.last(0) == []


def test_render():
    t = Transcript()
    assert t.render() == ""
    t.add("look", "West of House")
    assert t.render() == "> look\nWest of House"
