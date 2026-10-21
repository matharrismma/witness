"""The Palace — keep as a memory palace: loci on a room x position tensor, recall by a sort."""
from nh_org.palace import Palace


def test_keep_places_at_a_locus_and_persists(tmp_path):
    path = str(tmp_path / "palace.jsonl")
    r = Palace(path=path).keep(text="anxious about money", answer="I'm here.", kind="comfort", now=1.0)
    assert r["locus"] == {"room": "comfort", "position": 0}
    reopened = Palace(path=path)  # a fresh palace reads the same loci back from disk
    assert len(reopened.items) == 1 and reopened.items[0]["locus"]["room"] == "comfort"


def test_the_loci_form_a_room_by_position_tensor(tmp_path):
    p = Palace(path=str(tmp_path / "palace.jsonl"))
    p.keep(text="honest work", answer="a", kind="found", now=1.0)
    p.keep(text="a fair wage", answer="b", kind="found", now=2.0)
    p.keep(text="i feel low", answer="c", kind="comfort", now=3.0)
    assert p.rooms() == {"found": 2, "comfort": 1}
    assert p.shape() == {"rooms": 2, "max_positions": 2, "kept": 3}
    assert [it["locus"]["position"] for it in p.walk("found")] == [0, 1]  # walked along the position axis


def test_recall_sorts_by_relevance_then_recency(tmp_path):
    p = Palace(path=str(tmp_path / "palace.jsonl"))
    p.keep(text="the sabbath rest and honest labor", answer="", kind="found",
           theme="sabbath labor rest", now=1.0)
    p.keep(text="map projections and geometry", answer="", kind="found", theme="map geometry", now=2.0)
    hits = p.recall("honest labor", k=3)
    assert hits and hits[0]["theme"].startswith("sabbath"), hits
    assert all("score" in h for h in hits)


def test_recall_returns_nothing_on_no_overlap(tmp_path):
    p = Palace(path=str(tmp_path / "palace.jsonl"))
    p.keep(text="honest work", answer="", kind="found", now=1.0)
    assert p.recall("quantum chromodynamics") == []
