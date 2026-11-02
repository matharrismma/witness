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


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_commit_of_reads_head_from_the_files_git_keeps(tmp_path):
    """commit_of reads HEAD from the files git keeps: a detached id, or a refs/ ref from its loose file (in the git
    directory, then the common directory a worktree's commondir names) or else packed-refs; .git may be the
    directory or a file naming it. Anything else is "unknown", never a guess."""
    a, b, c, d, e = ("a1" * 20, "b2" * 20, "c3" * 20, "d4" * 20, "e5" * 20)
    repo = tmp_path / "repo"
    _write(repo / ".git" / "HEAD", "ref: refs/heads/main\n")
    _write(repo / ".git" / "refs" / "heads" / "main", a + "\n")
    assert serve.commit_of(repo) == a                                            # a loose ref
    packed = tmp_path / "packed"
    _write(packed / ".git" / "HEAD", "ref: refs/heads/main\n")
    _write(packed / ".git" / "packed-refs", f"# pack-refs with: peeled fully-peeled sorted\n{d} refs/heads/dev\n"
                                            f"{b} refs/heads/main\n^{c}\n{e} refs/tags/v1\n")
    assert serve.commit_of(packed) == b                                          # packed-refs, peeled line skipped
    _write(packed / ".git" / "refs" / "heads" / "main", e + "\n")
    assert serve.commit_of(packed) == e                                          # a loose ref wins over packed-refs
    _write(repo / ".git" / "HEAD", c + "\n")
    assert serve.commit_of(repo) == c                                            # detached
    _write(repo / ".git" / "HEAD", "f6" * 32 + "\n")
    assert serve.commit_of(repo) == "f6" * 32                                    # a sha-256 repository's id

    common = tmp_path / "main" / ".git"
    _write(common / "refs" / "heads" / "feature", d + "\n")
    _write(common / "worktrees" / "w" / "HEAD", "ref: refs/heads/feature\n")
    _write(common / "worktrees" / "w" / "commondir", "../..\n")
    wt = tmp_path / "wt"
    _write(wt / ".git", f"gitdir: {common / 'worktrees' / 'w'}\n")
    assert serve.commit_of(wt) == d                                              # a worktree, its ref in commondir
    rel = tmp_path / "rel"
    _write(rel / ".git", "gitdir: ../main/.git/worktrees/w\n")
    assert serve.commit_of(rel) == d                                             # a relative gitdir
    _write(common / "worktrees" / "w" / "HEAD", a + "\n")
    assert serve.commit_of(wt) == a                                              # a detached worktree, as the gate's

    nothing = tmp_path / "nothing"
    nothing.mkdir()
    assert serve.commit_of(nothing) == "unknown"                                 # not a git checkout
    assert serve.commit_of(tmp_path / "absent") == "unknown"
    bad = tmp_path / "bad"
    for head in ("hello\n", a.upper() + "\n", a[:-1] + "\n", a + "0\n", "ref: refs/heads/none\n", "ref: HEAD\n",
                 "ref: refs/../../escape\n", "ref:\n", ""):
        _write(bad / ".git" / "HEAD", head)
        assert serve.commit_of(bad) == "unknown", head
    _write(bad / "escape", a + "\n")                                             # where refs/../../escape lands
    _write(bad / ".git" / "HEAD", "ref: refs/../../escape\n")
    assert serve.commit_of(bad) == "unknown"                                     # a ref outside refs/ is refused
    (bad / ".git" / "HEAD").write_bytes(b"\xff\xfe\x00")
    assert serve.commit_of(bad) == "unknown"                                     # not text
    filed = tmp_path / "filed"
    _write(filed / ".git", "not a gitdir line\n")
    assert serve.commit_of(filed) == "unknown"
    _write(filed / ".git", "gitdir: ../nowhere\n")
    assert serve.commit_of(filed) == "unknown"
    empty = tmp_path / "empty"
    _write(empty / ".git" / "HEAD", "ref: refs/heads/main\n")
    assert serve.commit_of(empty) == "unknown"                                   # a repository with no commit yet


def test_commit_of_agrees_with_git_itself(tmp_path):
    """Against real git, isolated from this machine's configuration: commit_of equals `git rev-parse HEAD` on a
    branch, after the refs are packed, detached, and in a branch worktree and a detached one."""
    import shutil
    import subprocess
    if not shutil.which("git"):
        pytest.skip("git is not installed")
    (tmp_path / "gitconfig").write_text("", encoding="utf-8")
    inherited = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}   # no GIT_DIR from a caller
    env = {**inherited, "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"), "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args, cwd=repo):
        return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True,
                              text=True).stdout.strip()
    git("init", "-q")
    git("symbolic-ref", "HEAD", "refs/heads/main")
    assert serve.commit_of(repo) == "unknown"                                    # no commit yet
    for n in ("one", "two"):
        (repo / "f").write_text(n, encoding="utf-8")
        git("add", "f")
        git("commit", "-q", "-m", n)
        assert serve.commit_of(repo) == git("rev-parse", "HEAD")
    git("pack-refs", "--all")
    assert not (repo / ".git" / "refs" / "heads" / "main").exists()
    assert serve.commit_of(repo) == git("rev-parse", "HEAD")                    # read from packed-refs
    git("worktree", "add", "-q", "--detach", str(tmp_path / "wt"), "HEAD~1")
    assert serve.commit_of(tmp_path / "wt") == git("rev-parse", "HEAD", cwd=tmp_path / "wt") \
        == git("rev-parse", "HEAD~1")
    git("worktree", "add", "-q", "-b", "side", str(tmp_path / "side"))
    (tmp_path / "side" / "f").write_text("three", encoding="utf-8")
    git("commit", "-q", "-am", "three", cwd=tmp_path / "side")
    assert serve.commit_of(tmp_path / "side") == git("rev-parse", "HEAD", cwd=tmp_path / "side")
    git("checkout", "-q", "--detach", "HEAD~1")
    assert serve.commit_of(repo) == git("rev-parse", "HEAD")


def test_health_names_the_commit_read_once_at_startup(monkeypatch):
    """/health names the commit of the checkout that holds nh_org, read once when the app starts (at import), not
    per request; ok, surface and doors stand as before."""
    from pathlib import Path
    root = Path(serve.__file__).resolve().parent.parent
    assert serve.COMMIT == serve.commit_of(root)
    if (root / ".git").exists():                                                # a checkout, as here and in the gate
        assert serve._COMMIT_ID.fullmatch(serve.COMMIT), serve.COMMIT
    status, ctype, data = serve.handle("GET", "/health")
    body = json.loads(data)
    assert status == 200 and "json" in ctype and set(body) == {"ok", "surface", "commit", "doors"}
    assert body["commit"] == serve.COMMIT and body["ok"] and body["surface"] == "witness" and "/ask" in body["doors"]

    def read_again(*a):
        raise AssertionError("/health read the commit per request")
    monkeypatch.setattr(serve, "commit_of", read_again)
    monkeypatch.setattr(serve, "COMMIT", "f" * 40)
    assert json.loads(serve.handle("GET", "/health")[2])["commit"] == "f" * 40


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


def test_only_the_nine_doors_slashes_stripped_and_the_two_directory_doors_go_to_v3(monkeypatch):
    """A path goes to V3 only when, with any trailing slashes stripped, it IS one of the nine verification
    doors, or sits under one of the two directory doors /s/ and /schema/. A prefix is not a door:
    /find_verifier, /audit.html and /seal.html belong to the keeping's engine (on .org they answered V3's
    404, measured 2026-11-02). A door with trailing slashes stays with V3 for GET and POST alike: V3 strips
    them for its POST doors (POST /verify/ is /verify there) and matches GET exactly, so GET /seals/ is
    V3's 404 either way. The path is sent as given; only the choice of engine strips."""
    from urllib.parse import urlsplit

    from nh_org import core_client
    wire = _Wire()
    monkeypatch.setattr(core_client.urllib.request, "urlopen", wire)
    t = core_client.HttpTransport(base_url="http://keeping.test", verify_url="http://v3.test")
    h = "0" * 63 + "1"
    doors = ["/verify", "/seal", "/seals", "/discern", "/audit", "/scribe", "/find", "/capabilities",
             "/ledger/verify"]
    v3 = doors + [d + "/" for d in doors] + ["/verify//", "/s/" + h, "/schema/verify"]
    keeping = ["/find_verifier", "/find_verifier/", "/audit.html", "/seal.html", "/seal.html/",
               "/verify.html", "/sealed", "/seals.json", "/findx", "/scribe/x", "/capabilities.json",
               "/ledger/verify/x", "/ledger", "/ledger/", "/s", "/schema", "/ask", "/ask/", "/bible.html",
               "/", "//"]
    want = {**{p: "v3.test" for p in v3}, **{p: "keeping.test" for p in keeping}}
    for method in ("GET", "POST"):
        wire.requests.clear()
        for p in v3 + keeping:
            t.passthrough(method, p, "q=x", {} if method == "POST" else None)
        assert [r.get_method() for r in wire.requests] == [method] * len(want)
        assert [urlsplit(r.full_url).path for r in wire.requests] == v3 + keeping
        routed = {p: urlsplit(r.full_url).netloc for p, r in zip(v3 + keeping, wire.requests)}
        assert routed == want, method
    # the composed doors take the same rule
    wire.requests.clear()
    t.post("/verify", {"claim": "x"}, "seal=0")
    t.get("/seal", "hash=" + h)
    t.get("/mesh")
    assert [urlsplit(r.full_url).netloc for r in wire.requests] == ["v3.test", "v3.test", "keeping.test"]


class _Answer:
    """One stand-in response: what urlopen hands back for a 2xx."""

    def __init__(self, status, ctype, body):
        self.status, self.headers, self._body = status, {"content-type": ctype}, body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Engines(_Wire):
    """The _Wire stand-in with two engines on the line. Each host answers as it is told: a (status,
    content type, body), raised as urllib's HTTPError when it is a 4xx or 5xx, or None for no answer at
    all. Every Request is recorded, so a test sees which engine was asked and in what order."""

    def __init__(self, answers):
        super().__init__()
        self.answers = answers

    def __call__(self, req, timeout=None):
        import io
        import urllib.error
        from urllib.parse import urlsplit
        self.requests.append(req)
        answer = self.answers[urlsplit(req.full_url).netloc]
        if answer is None:
            raise urllib.error.URLError("no answer")
        status, ctype, body = answer
        if status >= 400:
            raise urllib.error.HTTPError(req.full_url, status, "stand-in", {"content-type": ctype},
                                         io.BytesIO(body))
        return _Answer(status, ctype, body)


H = "0123456789abcdef" * 4                      # a seal hash: 64 lowercase hex
V3_NOT_HELD = (404, "application/json", b'{"error": "seal not found"}')
HELD = (200, "text/html; charset=utf-8", b"<the keeping's receipt>")


def _two_engines(monkeypatch, v3, keeping, verify_url="http://v3.test"):
    """V3 at v3.test, the keeping's engine at keeping.test, each answering as told; no retries, so no
    test waits on a backoff."""
    from nh_org import core_client
    wire = _Engines({"v3.test": v3, "keeping.test": keeping})
    monkeypatch.setattr(core_client.urllib.request, "urlopen", wire)
    t = core_client.HttpTransport(base_url="http://keeping.test", verify_url=verify_url, retries=0)
    return wire, CoreClient(t)


def _asked(wire):
    """Every request the app made, in order: (method, engine, path, query)."""
    from urllib.parse import urlsplit
    return [(r.get_method(), *urlsplit(r.full_url)[1:4]) for r in wire.requests]


def test_a_seal_v3_does_not_hold_is_asked_of_the_keeping_and_its_answer_passed_through(monkeypatch):
    """GET /s/<64 lowercase hex> and GET /seal?hash=<64 lowercase hex> ask V3 first. Only V3's 404 sends
    the same request to the keeping's engine, and its answer comes back unchanged, whatever it is: status,
    content type, body (a receipt the keeping's engine sealed lives in its own ledger, not V3's; on .org
    it answered V3's 404, measured 2026-11-02). If the keeping gives no answer the app says so (503), never V3's 404, which
    would say that no engine holds it. Any other V3 outcome (200, any other 4xx, 5xx, no answer) is
    returned exactly as before and the keeping is never asked; so is V3's 404 to any other request, and
    one engine (NH_VERIFY_URL unset) is asked once."""
    seals = [("/s/" + H, ""), ("/seal", "hash=" + H)]
    # V3 does not hold it: the keeping's answer, whatever it is, comes back unchanged
    for keeping in (HELD, (200, "application/json", b'{"content_hash": "' + H.encode() + b'"}'),
                    (404, "text/plain", b"not held here either"), (500, "text/html", b"<keeping broke>")):
        for path, query in seals:
            wire, client = _two_engines(monkeypatch, V3_NOT_HELD, keeping)
            assert serve.handle("GET", path, query, client=client) == keeping
            assert _asked(wire) == [("GET", "v3.test", path, query), ("GET", "keeping.test", path, query)]
    for path, query in seals:
        wire, client = _two_engines(monkeypatch, V3_NOT_HELD, None)
        status, _c, data = serve.handle("GET", path, query, client=client)
        assert status == 503 and b"nothing was fabricated" in data and b"keeping.test" in data
        assert _asked(wire) == [("GET", "v3.test", path, query), ("GET", "keeping.test", path, query)]
    # any other V3 outcome stands, and the keeping is never asked
    for v3 in ((200, "application/json", b'{"v3": "held"}'), (400, "application/json", b'{"error": "bad"}'),
               (403, "text/plain", b"forbidden"), (410, "text/plain", b"gone"),
               (429, "application/json", b'{"error": "slow down"}'), (500, "text/plain", b"v3 broke"),
               (502, "text/html", b"<bad gateway>"), (503, "application/json", b'{"error": "busy"}')):
        for path, query in seals:
            wire, client = _two_engines(monkeypatch, v3, HELD)
            assert serve.handle("GET", path, query, client=client) == v3
            assert _asked(wire) == [("GET", "v3.test", path, query)]
    for path, query in seals:
        wire, client = _two_engines(monkeypatch, None, HELD)
        status, _c, data = serve.handle("GET", path, query, client=client)
        assert status == 503 and b"nothing was fabricated" in data and b"v3.test" in data
        assert _asked(wire) == [("GET", "v3.test", path, query)]
    # only those two requests: V3's 404 to anything else stands, and the keeping is never asked
    not_the_form = [("GET", "/s/" + H.upper(), ""), ("GET", "/s/" + H[:-1], ""), ("GET", "/s/" + H + "0", ""),
                    ("GET", "/s/" + H + "/", ""), ("GET", "/s/" + H + "/x", ""), ("GET", "/s/" + H, "format=json"),
                    ("GET", "/seal", "hash=" + H.upper()), ("GET", "/seal", "hash=" + H[:-1]),
                    ("GET", "/seal", "hash=" + H + "&x=1"), ("GET", "/seal", "x=1&hash=" + H), ("GET", "/seal", ""),
                    ("GET", "/seal/", "hash=" + H), ("GET", "/seals", "hash=" + H), ("GET", "/schema/" + H, ""),
                    ("GET", "/verify", "hash=" + H), ("POST", "/s/" + H, ""), ("POST", "/seal", "hash=" + H)]
    for method, path, query in not_the_form:
        wire, client = _two_engines(monkeypatch, V3_NOT_HELD, HELD)
        body = {} if method == "POST" else None
        assert serve.handle(method, path, query, body, client=client) == V3_NOT_HELD, (method, path, query)
        assert _asked(wire) == [(method, "v3.test", path, query)]
    # one engine: it is asked once, and its 404 stands
    monkeypatch.delenv("NH_VERIFY_URL", raising=False)
    for path, query in seals:
        wire, client = _two_engines(monkeypatch, None, V3_NOT_HELD, verify_url=None)
        assert serve.handle("GET", path, query, client=client) == V3_NOT_HELD
        assert _asked(wire) == [("GET", "keeping.test", path, query)]


def test_the_record_lookup_follows_the_same_seal_rule(monkeypatch):
    """record.fetch (GET /seal?hash=<hash>) takes the same rule: only V3's 404 asks the keeping's engine,
    whose answer stands: its record, None on its 404, or CoreUnavailable on its other error or no answer.
    Any other V3 outcome is returned exactly as before (V3's record, or CoreUnavailable naming V3), the
    keeping never asked; so is any other request, and one engine is asked once."""
    from nh_org import record
    from nh_org.core_client import CoreUnavailable
    rec = {"content_hash": H, "kind": "the keeping's record"}
    held = (200, "application/json", json.dumps(rec).encode())
    v3_asked = [("GET", "v3.test", "/seal", "hash=" + H)]
    both_asked = v3_asked + [("GET", "keeping.test", "/seal", "hash=" + H)]
    # V3 does not hold it: the keeping's answer stands
    wire, client = _two_engines(monkeypatch, V3_NOT_HELD, held)
    assert record.fetch(H, client=client) == rec
    assert _asked(wire) == both_asked
    wire, client = _two_engines(monkeypatch, V3_NOT_HELD, (404, "application/json", b'{"error": "not found"}'))
    assert record.fetch(H, client=client) is None
    assert _asked(wire) == both_asked
    for keeping in ((500, "text/html", b"<keeping broke>"), None):
        wire, client = _two_engines(monkeypatch, V3_NOT_HELD, keeping)
        with pytest.raises(CoreUnavailable, match="keeping.test"):
            record.fetch(H, client=client)
        assert _asked(wire) == both_asked
    # any other V3 outcome stands, and the keeping is never asked
    wire, client = _two_engines(monkeypatch, (200, "application/json", b'{"v3": "held"}'), held)
    assert record.fetch(H, client=client) == {"v3": "held"}
    assert _asked(wire) == v3_asked
    for v3 in ((400, "application/json", b'{"error": "bad"}'), (429, "application/json", b"{}"),
               (500, "text/plain", b"v3 broke"), (503, "application/json", b"{}"), None):
        wire, client = _two_engines(monkeypatch, v3, held)
        with pytest.raises(CoreUnavailable, match="v3.test"):
            record.fetch(H, client=client)
        assert _asked(wire) == v3_asked
    # only the exact request: V3's 404 to anything else stands
    wire, client = _two_engines(monkeypatch, V3_NOT_HELD, held)
    assert record.fetch(H.upper(), client=client) is None
    assert _asked(wire) == [("GET", "v3.test", "/seal", "hash=" + H.upper())]
    wire, client = _two_engines(monkeypatch, V3_NOT_HELD, held)
    with pytest.raises(CoreUnavailable, match="404"):
        client.t.get("/seal", "hash=" + H + "&x=1")
    assert _asked(wire) == [("GET", "v3.test", "/seal", "hash=" + H + "&x=1")]
    # one engine: it is asked once, and its 404 stands
    monkeypatch.delenv("NH_VERIFY_URL", raising=False)
    wire, client = _two_engines(monkeypatch, None, V3_NOT_HELD, verify_url=None)
    assert record.fetch(H, client=client) is None
    assert _asked(wire) == [("GET", "keeping.test", "/seal", "hash=" + H)]


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
