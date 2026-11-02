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


class _ProxyFake:
    """A transport that records the proxied request and returns a stand-in core response."""

    def __init__(self):
        self.seen = None

    def passthrough(self, method, path, query="", body=None):
        self.seen = (method, path, query)
        return 200, "text/html; charset=utf-8", f"<core witness page for {path}>".encode()


def test_unowned_paths_pass_through_to_the_core():
    """The .org front: a path the app does not own (e.g. /bible.html) is served by the core verbatim,
    so the full witness site stays whole after the flip — not a 404."""
    t = _ProxyFake()
    status, ctype, data = serve.handle("GET", "/bible.html", client=CoreClient(t))
    assert status == 200 and b"core witness page for /bible.html" in data
    assert t.seen == ("GET", "/bible.html", "")


class _Wire:
    """Stands in for urllib's opener: records every Request and answers with a small JSON body."""

    def __init__(self):
        self.requests = []

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        return self

    status = 200
    headers = {"content-type": "application/json"}

    def read(self):
        return b'{"ok": true}'

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_the_client_address_rides_to_the_core_as_x_forwarded_for(monkeypatch):
    """Every request this app makes to the core carries the visitor's address, verbatim as Caddy handed it
    here (its last hop is the real client) — never this app's own peer appended. Without it every
    narrowhighway.org visitor shared one 127.0.0.1 rate-limit bucket at the core with the deploy gate
    itself (measured 2026-11-01). A call that arrived with no such header sends none."""
    from nh_org import core_client
    wire = _Wire()
    monkeypatch.setattr(core_client.urllib.request, "urlopen", wire)
    t = core_client.HttpTransport(base_url="http://core.test", forwarded_for="203.0.113.9, 198.51.100.7")
    t.post("/ask", {"text": "x"})
    t.get("/seals")
    t.passthrough("GET", "/search", "q=x")
    t.passthrough("POST", "/ask", body={"text": "y"})
    t.post_raw("/speak", {"text": "z"})
    assert len(wire.requests) == 5
    for req in wire.requests:
        assert req.get_header("X-forwarded-for") == "203.0.113.9, 198.51.100.7"
    assert wire.requests[0].get_header("Content-type") == "application/json"   # the other headers stand
    plain = _Wire()
    monkeypatch.setattr(core_client.urllib.request, "urlopen", plain)
    core_client.HttpTransport(base_url="http://core.test").passthrough("GET", "/bible.html")
    core_client.HttpTransport(base_url="http://core.test", forwarded_for="  ").get("/seals")
    assert all(r.get_header("X-forwarded-for") is None for r in plain.requests)


def test_only_exact_verification_doors_and_the_two_directory_doors_go_to_v3(monkeypatch):
    """A path goes to V3 only when it IS a verification door, or sits under one of the two directory
    doors /s/ and /schema/. A prefix is not a door: /find_verifier, /audit.html and /seal.html belong to
    the keeping's engine (on .org they answered V3's 404, measured 2026-11-02)."""
    from urllib.parse import urlsplit

    from nh_org import core_client
    wire = _Wire()
    monkeypatch.setattr(core_client.urllib.request, "urlopen", wire)
    t = core_client.HttpTransport(base_url="http://keeping.test", verify_url="http://v3.test")
    h = "0" * 63 + "1"
    v3 = ["/verify", "/seal", "/seals", "/discern", "/audit", "/scribe", "/find", "/capabilities",
          "/ledger/verify", "/s/" + h, "/schema/verify"]
    keeping = ["/find_verifier", "/audit.html", "/seal.html", "/verify.html", "/verify/", "/sealed",
               "/seals.json", "/findx", "/scribe/x", "/capabilities.json", "/ledger/verify/x", "/ledger",
               "/s", "/schema", "/ask", "/bible.html", "/"]
    for p in v3 + keeping:
        t.passthrough("GET", p, "q=x")
    routed = {p: urlsplit(r.full_url).netloc for p, r in zip(v3 + keeping, wire.requests)}
    assert routed == {**{p: "v3.test" for p in v3}, **{p: "keeping.test" for p in keeping}}
    # the composed doors take the same rule
    wire.requests.clear()
    t.post("/verify", {"claim": "x"}, "seal=0")
    t.get("/seal", "hash=" + h)
    t.get("/mesh")
    assert [urlsplit(r.full_url).netloc for r in wire.requests] == ["v3.test", "v3.test", "keeping.test"]


def test_handle_threads_the_forwarded_address_into_the_client(monkeypatch):
    """The server hands the header it received to the client it builds for that one request."""
    built = {}

    class _Client:
        def __init__(self, transport=None, forwarded_for=None):
            built["forwarded_for"] = forwarded_for

        def passthrough(self, method, path, query="", body=None):
            return 200, "text/html", b"<core>"
    monkeypatch.setattr(serve, "CoreClient", _Client)
    status, _c, data = serve.handle("GET", "/bible.html", forwarded_for="198.51.100.7")
    assert status == 200 and built["forwarded_for"] == "198.51.100.7"


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
