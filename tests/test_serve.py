"""The witness web server — routing tested without sockets, against recorded core responses."""
import json
import os

import pytest

from nh_org import serve
from nh_org.core_client import CoreClient, RecordedTransport

HERE = os.path.dirname(os.path.abspath(__file__))
CONSOLE_FIX = os.path.join(HERE, "fixtures", "console_recorded.json")


def test_health_lists_the_doors():
    status, ctype, data = serve.handle("GET", "/health")
    assert status == 200 and "json" in ctype
    body = json.loads(data)
    assert body["ok"] and body["surface"] == "witness" and "/ask" in body["doors"]


def test_landing_is_a_still_page_with_an_ask_box():
    status, ctype, data = serve.handle("GET", "/")
    h = data.decode()
    assert status == 200 and "text/html" in ctype
    assert '<form action="/book"' in h
    assert ":root{--bg" in h and "{{" not in h  # the CSS braces are single, not a stray format string
    assert "<script" not in h


def test_unknown_door_is_404_json():
    status, _c, data = serve.handle("GET", "/nope")
    assert status == 404 and "no such door" in json.loads(data)["error"]


def test_console_requires_text():
    status, _c, data = serve.handle("POST", "/console", body={})
    assert status == 400


@pytest.mark.skipif(not os.path.exists(CONSOLE_FIX), reason="run tools/record_console.py first")
def test_book_renders_a_recorded_answer_as_a_page():
    client = CoreClient(RecordedTransport(json.load(open(CONSOLE_FIX, encoding="utf-8"))))
    q = "what does scripture say about honest work"
    status, ctype, data = serve.handle("GET", "/book", "q=" + q.replace(" ", "+"), client=client, gate_open=True)
    h = data.decode()
    assert status == 200 and "text/html" in ctype
    assert h.startswith("<!doctype html>") and "<main>" in h
    assert "Next." in h  # the gate-open answer carries a shepherd's next step, rendered on the page


@pytest.mark.skipif(not os.path.exists(CONSOLE_FIX), reason="run tools/record_console.py first")
def test_console_returns_json_payload():
    client = CoreClient(RecordedTransport(json.load(open(CONSOLE_FIX, encoding="utf-8"))))
    status, ctype, data = serve.handle("POST", "/console", body={"text": "how many ounces in a pound"},
                                       client=client, gate_open=False)
    assert status == 200 and "json" in ctype
    out = json.loads(data)
    assert out["answer"] and out["generated"] is False
