"""The BOOK render — a still, standalone page of what the core returned; escaped, themed, no script."""
import html
import json
import os

import pytest

from nh_org import console
from nh_org.console import book
from nh_org.core_client import CoreClient, RecordedTransport

HERE = os.path.dirname(os.path.abspath(__file__))
RECORDING = os.path.join(HERE, "fixtures", "console_recorded.json")


def test_render_is_a_standalone_escaped_page():
    payload = {
        "answer": "Work heartily, as for the Lord.\nIt is the Lord Christ you serve.",
        "word": {"ref": "Colossians 3:23", "text": "Whatever you do, work heartily."},
        "trail": [{"domain": "scripture", "status": "CONFIRMED", "detail": "found + cited"}],
        "cloud": {"witnesses": [{"title": "Spurgeon on labor", "shares": "the dignity of work"}]},
        "next_step": {"do": "Read Colossians 3:23 in its own words.", "door": "WORD"},
        "verify": {"receipt": "https://narrowhighway.org/s/abc123"},
    }
    h = book.render(payload)
    assert h.startswith("<!doctype html>") and "<main>" in h and "</html>" in h
    assert "Work heartily, as for the Lord." in h and "Colossians 3:23" in h
    assert "Spurgeon on labor" in h and "Read Colossians 3:23" in h
    assert "narrowhighway.org/s/abc123" in h


def test_render_escapes_interpolated_content():
    h = book.render({"answer": "<script>alert(1)</script> & co", "next_step": {"do": "<b>x</b>"}})
    assert "<script>alert(1)</script>" not in h
    assert "&lt;script&gt;" in h and "&amp; co" in h and "&lt;b&gt;x&lt;/b&gt;" in h


def test_render_is_theme_aware_and_motionless():
    h = book.render({"answer": "hello"})
    assert "prefers-color-scheme:dark" in h and ':root[data-theme=dark]' in h
    assert "background:var(--bg)" in h
    assert "<script" not in h  # a still page runs no script


@pytest.mark.skipif(not os.path.exists(RECORDING), reason="run tools/record_console.py first")
def test_render_a_recorded_answer():
    client = CoreClient(RecordedTransport(json.load(open(RECORDING, encoding="utf-8"))))
    out = console.dispatch("what does scripture say about honest work", client=client, gate_open=True)
    h = book.render(out, title="The Console")
    # the answer is on the page, escaped as the renderer escapes it (apostrophes etc.)
    assert html.escape(out["answer"]).split("\n")[0][:20] in h
    assert out["word"]["ref"] in h  # the Word is set on the page
