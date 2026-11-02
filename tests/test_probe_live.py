"""tools/probe_live.py — the live probe, against stand-ins for the network. Never the network itself."""
import hashlib
import http.client
import importlib.util
import io
import json
import os
import runpy
import urllib.error
import urllib.request
from urllib.parse import parse_qs, urlsplit

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROBE = os.path.join(ROOT, "tools", "probe_live.py")

ORG, COM, API = "https://narrowhighway.org", "https://narrowhighway.com", "https://api.narrowhighway.com"
# the run's sample hashes, as the lead's before-note records them (docs/harness/runs/2026-11-02-receipts-open.jsonl)
C2_AFTER = "045bc6ffa8725277ddf45a65e256965641e6c9f0b7d761094e5286a85c359ad8"
C2_BEFORE = "fcf98a9efde9758f21f26eb8d92281a2e5fc38a4c55c787b0577e507aa484745"
V3 = "75cf60e58c6f5a2189c9c76d6235e95eea99676e10379ef22f8bfa9de194ac98"
PROF = "786c40536bbc987b29ab74f85a38003a550ad14164a7d6ad73787922c926f2b9"
UNHELD = "0" * 63 + "1"
VERIFY = ("POST", ORG + "/verify?seal=0", {"claim": "1234+4321=5555"})
CONSOLE = ("POST", ORG + "/console", {"text": "how many ounces in a pound"})
V3_COUNT, C2_COUNT = ORG + "/seals?limit=200", COM + "/seals"
COUNT_READS = [("GET", V3_COUNT, None), ("GET", C2_COUNT, None)]


def _probe():
    """Load tools/probe_live.py by path, inside the test, so a missing probe fails the test itself."""
    spec = importlib.util.spec_from_file_location("probe_live", PROBE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Touched(BaseException):
    """Raised by any real HTTP attempt. A BaseException, so the probe's own `except Exception` cannot swallow
    it into a reported error: the test fails."""


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Belt and braces: any real HTTP attempt during these tests fails the test loudly."""
    def refuse(*a, **k):
        raise _Touched("a probe test touched the network")
    monkeypatch.setattr(http.client.HTTPConnection, "connect", refuse)
    monkeypatch.setattr(http.client.HTTPSConnection, "connect", refuse)
    monkeypatch.setattr(urllib.request, "urlopen", refuse)


class _Stand:
    """Stands in for the network as a transport: records every (method, url, body) the probe sends and answers
    from a table keyed by exact URL; an answer may be a (status, content type, body), a function of the request
    returning one, or an exception to raise (no answer). An unlisted URL answers 200 with an empty JSON object."""

    def __init__(self, answers=None):
        self.calls = []
        self.answers = answers or {}

    def __call__(self, method, url, body):
        self.calls.append((method, url, body))
        a = self.answers.get(url, (200, "application/json", b"{}"))
        if callable(a):
            a = a(method, url, body)
        if isinstance(a, Exception):
            raise a
        return a


class _Resp:
    """What urllib's opener hands back for a 2xx."""

    def __init__(self, status, ctype, body):
        self.status, self.headers, self._body = status, {"content-type": ctype}, body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Net:
    """Stands in for urllib's opener under the probe's own transport (http): build_opener returns it, and it
    records every Request and every handler set it was built with. It answers from the same kind of table as
    _Stand, keyed by exact URL; a status of 300 or more is raised as urllib's HTTPError, as urllib does once a
    redirect is refused."""

    def __init__(self, answers=None):
        self.sent, self.handlers = [], []
        self.answers = answers or {}

    def build_opener(self, *handlers):
        self.handlers.append(handlers)
        return self

    def open(self, req, timeout=None):
        self.sent.append(req)
        a = self.answers.get(req.full_url, (200, "application/json", b"{}"))
        if callable(a):
            a = a(req.get_method(), req.full_url, None if req.data is None else json.loads(req.data))
        status, ctype, body = a
        if status >= 300:
            raise urllib.error.HTTPError(req.full_url, status, "stand-in", {"content-type": ctype}, io.BytesIO(body))
        return _Resp(status, ctype, body)

    def calls(self):
        return [(r.get_method(), r.full_url, None if r.data is None else json.loads(r.data)) for r in self.sent]


def _run_script(monkeypatch, capsys, net):
    """Run tools/probe_live.py exactly as `python tools/probe_live.py` does (as __main__, its own default
    transport), with urllib's opener replaced by `net`. Returns (exit code, the one JSON object it printed)."""
    monkeypatch.setattr(urllib.request, "build_opener", net.build_opener)
    with pytest.raises(SystemExit) as ended:
        runpy.run_path(PROBE, run_name="__main__")
    return ended.value.code, json.loads(capsys.readouterr().out)


def _counts_ok():
    v3 = {"count": 3, "seals": [{"content_hash": h} for h in ("c" * 64, "b" * 64, "a" * 64)]}
    c2 = {"seals": {"minted": 1808, "cas_records": 3154, "total_checksum": {"root": "9" * 64, "count": 3160}}}
    return {V3_COUNT: (200, "application/json", json.dumps(v3).encode()),
            C2_COUNT: (200, "application/json", json.dumps(c2).encode())}


def test_the_probe_writes_nothing_its_only_posts_are_the_two_and_every_verify_carries_seal_0(monkeypatch, capsys):
    """Run as `python tools/probe_live.py` runs it: the script sends exactly the counts, then every entry of
    REQUESTS, then the counts, and nothing else. Its only POSTs are POST /verify?seal=0 with the claim
    1234+4321=5555 and POST /console with the ounces question; everything else is a GET with no body, to the
    three public hosts; every request to a door that seals by default carries seal=0; every opener refuses
    redirects, so a 3xx is reported as its own answer. It exits 0 when the counts hold."""
    p = _probe()
    net = _Net({**_counts_ok(), ORG + "/health": (302, "text/html", b"moved")})
    code, out = _run_script(monkeypatch, capsys, net)
    sent = net.calls()
    assert sent == COUNT_READS + list(p.REQUESTS) + COUNT_READS
    assert code == 0 and out["counts_unchanged"] is True
    assert [c for c in sent if c[0] != "GET"] == [VERIFY, CONSOLE]
    assert [c for c in p.REQUESTS if c[0] != "GET"] == [VERIFY, CONSOLE]
    sealing = []
    for (method, url, body), req in zip(sent, net.sent):
        u = urlsplit(url)
        assert u.scheme == "https" and u.netloc in ("narrowhighway.org", "narrowhighway.com", "api.narrowhighway.com")
        if u.path.rstrip("/") in ("/verify", "/audit"):          # V3 seals both by default
            assert parse_qs(u.query, keep_blank_values=True) == {"seal": ["0"]}, url
            sealing.append(url)
        assert req.get_header("User-agent") == p.USER_AGENT
        if method == "GET":
            assert body is None and req.data is None
        else:
            assert req.get_header("Content-type") == "application/json"
    assert sealing == [ORG + "/verify?seal=0"]
    assert len(net.handlers) == len(net.sent)                       # one opener per request, each refusing redirects
    for handlers in net.handlers:
        assert len(handlers) == 1 and handlers[0].__name__ == "_NoRedirect"
        assert issubclass(handlers[0], urllib.request.HTTPRedirectHandler)
        assert handlers[0]().redirect_request(net.sent[0], None, 302, "Found", {}, "https://elsewhere.test/") is None
    assert out["requests"]["GET " + ORG + "/health"]["status"] == 302    # a refused redirect is its own answer
    assert list(out["requests"]) == [f"{m} {u}" for m, u, _b in p.REQUESTS]


def test_the_requests_cover_every_live_check_of_the_plan():
    """Every live check the plan names is a request the probe makes: the four sample hashes and the unheld one
    at /s/ and /seal?hash= on the hosts named, /find_verifier on .org and api., the three pages, the .org
    read surfaces and the two POSTs. No request repeats; the counts are read first and last."""
    p = _probe()
    need = []
    for h, hosts in ((C2_AFTER, (ORG, COM)), (C2_BEFORE, (ORG, COM)), (PROF, (ORG, COM)), (V3, (ORG, API)),
                     (UNHELD, (ORG,))):
        for host in hosts:
            need += [("GET", f"{host}/s/{h}"), ("GET", f"{host}/seal?hash={h}")]
    need += [("GET", ORG + "/find_verifier?q=speed+of+light"), ("GET", API + "/find_verifier?q=speed+of+light")]
    need += [("GET", ORG + p_) for p_ in ("/audit.html", "/seal.html", "/proof.html", "/find?q=speed+of+light",
                                          "/book", "/seals", "/capabilities", "/health")]
    need += [VERIFY[:2], CONSOLE[:2]]
    asked = [(m, u) for m, u, _b in p.REQUESTS]
    assert sorted(asked) == sorted(need) and len(set(asked)) == len(asked)
    wire = _Stand(_counts_ok())
    out = p.run(wire)
    assert list(out["requests"]) == [f"{m} {u}" for m, u in asked]
    assert wire.calls == COUNT_READS + list(p.REQUESTS) + COUNT_READS


def test_each_answer_reports_status_type_bytes_and_the_full_sha256():
    """status, type (without parameters), bytes and the sha256 of the body as received (all 64 hex); when no
    answer comes, the error instead. The /console, /capabilities and /health fields are read as defined."""
    p = _probe()
    proof = b"<!doctype html><title>proof</title>\xe2\x80\x94"
    console = json.dumps({"answer": "There are 16 ounces in a pound."}).encode()
    health = {"ok": True, "surface": "witness", "commit": "d02500c"}
    wire = _Stand({**_counts_ok(),
                   ORG + "/proof.html": (200, "text/html; charset=utf-8", proof),
                   ORG + "/audit.html": (404, "text/plain", b"not found"),
                   ORG + "/book": urllib.error.URLError("down"),
                   ORG + "/console": (200, "application/json; charset=utf-8", console),
                   ORG + "/capabilities": (200, "application/json", b'{"version": "3.0.0a0", "tools": []}'),
                   ORG + "/health": (200, "application/json", json.dumps(health).encode())})
    r = p.run(wire)["requests"]
    assert r["GET " + ORG + "/proof.html"] == {"status": 200, "type": "text/html", "bytes": len(proof),
                                               "sha256": hashlib.sha256(proof).hexdigest()}
    assert len(r["GET " + ORG + "/proof.html"]["sha256"]) == 64
    assert r["GET " + ORG + "/audit.html"] == {"status": 404, "type": "text/plain", "bytes": 9,
                                               "sha256": hashlib.sha256(b"not found").hexdigest()}
    assert r["GET " + ORG + "/book"] == {"error": "URLError: <urlopen error down>"}
    assert r["POST " + ORG + "/console"]["says_16_ounces"] is True
    assert r["GET " + ORG + "/capabilities"]["version"] == "3.0.0a0"
    assert r["GET " + ORG + "/health"]["health"] == health
    assert p.derived(ORG + "/console", 200, b'{"answer": "16 ounce"}') == {"says_16_ounces": False}
    assert p.derived(ORG + "/capabilities", 200, b"<html>") == {"version": None}
    assert p.derived(ORG + "/health", 200, b"[1]") == {"health": None}


def test_body_names_hash_is_the_hash_in_the_decoded_body():
    """For a URL carrying a sample hash: whether the body, decoded as UTF-8 with bad bytes replaced, contains
    that hash's 64 hex characters, exactly. Absent for a URL that carries none."""
    p = _probe()
    d = p.derived
    assert d(ORG + "/s/" + C2_AFTER, 200, b"<p>\xff the receipt " + C2_AFTER.encode() + b"</p>")["body_names_hash"]
    assert d(ORG + "/seal?hash=" + C2_AFTER, 404, b'{"error": "seal not found"}') == {"body_names_hash": False}
    assert d(COM + "/s/" + PROF, 200, PROF.upper().encode())["body_names_hash"] is False
    assert d(COM + "/s/" + PROF, 200, PROF[:-1].encode())["body_names_hash"] is False
    assert d(ORG + "/s/" + UNHELD, 200, V3.encode())["body_names_hash"] is False      # another hash is not this one
    assert "body_names_hash" not in d(ORG + "/proof.html", 200, V3.encode())


def test_record_sans_attest_is_the_sorted_compact_sha256_without_attest():
    """For a seal request answered 200 with a JSON object: sha256 of json.dumps(the object without its top-level
    attest, sort_keys=True, separators=(",", ":")). V3 re-signs attest per request, so two answers that differ
    only there share the digest; any other change moves it. Absent for HTML, non-200 or a non-object."""
    p = _probe()
    d = p.derived
    first = b'{"b": "x", "attest": {"sig": "first"}, "a": 1}'
    second = b'{\n "a": 1,\n "attest": {"sig": "second"},\n "b": "x"\n}'
    canonical = hashlib.sha256(b'{"a":1,"b":"x"}').hexdigest()
    assert d(ORG + "/s/" + V3, 200, first)["record_sans_attest"] == canonical
    assert d(ORG + "/seal?hash=" + V3, 200, second)["record_sans_attest"] == canonical
    assert d(API + "/s/" + V3, 200, b'{"a": 2, "b": "x", "attest": {}}')["record_sans_attest"] != canonical
    nested = d(API + "/seal?hash=" + V3, 200, b'{"a": 1, "b": "x", "c": {"attest": 1}}')["record_sans_attest"]
    assert nested == hashlib.sha256(b'{"a":1,"b":"x","c":{"attest":1}}').hexdigest()    # only the top level
    assert d(ORG + "/s/" + V3, 200, '{"t": "é"}'.encode())["record_sans_attest"] == \
        hashlib.sha256(b'{"t":"\\u00e9"}').hexdigest()                                   # json.dumps' ASCII form
    assert "record_sans_attest" not in d(COM + "/s/" + C2_AFTER, 200, b"<html>receipt</html>")
    assert "record_sans_attest" not in d(ORG + "/s/" + UNHELD, 404, b'{"error": "seal not found"}')
    assert "record_sans_attest" not in d(ORG + "/seal?hash=" + V3, 200, b"[1, 2]")
    assert "record_sans_attest" not in d(ORG + "/seals", 200, first)


def test_seal_hashes_are_the_sorted_content_hashes_seals_lists():
    """For a /seals answer whose JSON "seals" is a list: its entries' content_hash strings, sorted. Absent when
    "seals" is not a list (concordance-2's /seals is a summary object) or the body is not JSON."""
    p = _probe()
    d = p.derived
    body = json.dumps({"count": 3, "seals": [{"content_hash": "c" * 64}, {"content_hash": "a" * 64},
                                             {"summary": "no hash"}, "junk", {"content_hash": 7},
                                             {"content_hash": "b" * 64}]}).encode()
    assert d(ORG + "/seals", 200, body) == {"seal_hashes": ["a" * 64, "b" * 64, "c" * 64]}
    assert d(COM + "/seals", 200, b'{"seals": {"minted": 1808}}') == {}
    assert d(ORG + "/seals", 200, b"<html>") == {}
    wire = _Stand({**_counts_ok(), ORG + "/seals": (200, "application/json", body)})
    assert p.run(wire)["requests"]["GET " + ORG + "/seals"]["seal_hashes"] == ["a" * 64, "b" * 64, "c" * 64]


def test_sealed_is_a_seal_at_the_top_level_or_under_house():
    """For a /verify answer: sealed is whether its JSON object carries a non-empty seal at the top level (V3) or
    under house (concordance-2), the two places CoreClient.seal_of reads; verdict is its verdict. Both None when
    the body is not a JSON object."""
    p = _probe()
    url = ORG + "/verify?seal=0"
    seal = {"content_hash": "e" * 64, "cite_url": ORG + "/s/" + "e" * 64}
    cases = [({"verdict": "HOLDS", "seal": None}, False), ({"verdict": "HOLDS"}, False),
             ({"verdict": "HOLDS", "seal": {}}, False), ({"verdict": "HOLDS", "house": "x"}, False),
             ({"verdict": "HOLDS", "house": {"seal": None}}, False),
             ({"verdict": "HOLDS", "seal": seal}, True), ({"verdict": "HOLDS", "house": {"seal": seal}}, True)]
    for body, sealed in cases:
        assert p.derived(url, 200, json.dumps(body).encode()) == {"sealed": sealed, "verdict": "HOLDS"}, body
    assert p.derived(url, 502, b"<html>bad gateway</html>") == {"sealed": None, "verdict": None}
    sealed_answer = json.dumps({"verdict": "HOLDS", "seal": seal}).encode()
    wire = _Stand({**_counts_ok(), url: (200, "application/json", sealed_answer)})
    r = p.run(wire)["requests"]["POST " + url]
    assert (r["sealed"], r["verdict"]) == (True, "HOLDS")


def _moving(change):
    """Count answers for both engines, shaped as _counts_ok's, where concordance-2's answer changes by
    `change(c2)` once the probe's POST /verify?seal=0 has been sent (a stand-in engine that writes, to prove the
    counts catch it). V3 holds steady at 3."""
    posted = []

    def count(method, url, body):
        v3 = {"count": 3, "seals": [{"content_hash": h} for h in ("c" * 64, "b" * 64, "a" * 64)]}
        c2 = {"seals": {"minted": 1808, "cas_records": 3154, "total_checksum": {"root": "9" * 64, "count": 3160}}}
        if posted:
            change(c2)
        return 200, "application/json", json.dumps(v3 if url == V3_COUNT else c2).encode()

    def verify(method, url, body):
        posted.append(url)
        return 200, "application/json", b'{"verdict": "HOLDS", "seal": null}'
    return {V3_COUNT: count, C2_COUNT: count, ORG + "/verify?seal=0": verify}


def _v3_slug(value):
    """Concordance-V3 ledger.py:282-293 (_slugify), the name a ledger file takes."""
    out = []
    for c in value.lower():
        if c.isalnum():
            out.append(c)
        elif c in (" ", "-", "_", ".", "/", ":"):
            out.append("-")
    slug = "".join(out)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "untitled"


class _V3Ledger:
    """Stands in for V3's GET /seals?limit=200, built the way V3's own route builds it: a seal's ledger file is
    named for the slug of "<axis>/<first 16 hex of its hash>" (receipts.py:152, ledger.py:349); the route reads
    the files sorted by name (ledger.py:59), keeps the last `limit`, at most 200, and reverses them
    (http_api.py:293-294). `seal_on_verify` names the axis a POST /verify?seal=0 would seal under, to prove the
    probe's judgment holds even when a write happens."""

    def __init__(self, held=(), seal_on_verify=None):
        self.files = {}
        for axis, h in held:
            self.seal(axis, h)
        self.seal_on_verify = seal_on_verify

    def seal(self, axis, h):
        self.files[_v3_slug(f"{axis}/{h[:16]}") + ".json"] = h

    def seals(self, method, url, body):
        lim = max(1, min(200, int(parse_qs(urlsplit(url).query).get("limit", ["20"])[0])))
        entries = [self.files[name] for name in sorted(self.files)][-lim:][::-1]
        body = {"count": len(entries), "seals": [{"content_hash": h} for h in entries]}
        return 200, "application/json", json.dumps(body).encode()

    def verify(self, method, url, body):
        if self.seal_on_verify:
            self.seal(self.seal_on_verify, hashlib.sha256(json.dumps(body).encode()).hexdigest())
        return 200, "application/json", b'{"verdict": "HOLDS", "seal": null}'

    def answers(self):
        return {**_counts_ok(), V3_COUNT: self.seals, ORG + "/verify?seal=0": self.verify}


def _h(label):
    return hashlib.sha256(label.encode()).hexdigest()


def test_the_seal_counts_are_read_before_and_after_and_must_not_move(monkeypatch, capsys):
    """Read before and after: V3's /seals count and every content_hash it lists; concordance-2's seals.minted
    and its live seals.total_checksum count and root; and its seals.cas_records, an hourly copy, reported but not
    judged. V3 is judged only while its count is below 200 both times: at 200 a new seal can fall outside the 200
    it lists (its route orders by file name, not by time) and leave count and list unchanged, so there V3 is
    reported not judged and counts_unchanged is false. counts_unchanged (and exit 0) only when V3 is judged and
    every judged field was read both times and none moved. Run as a script, it exits 1 otherwise."""
    p = _probe()
    want = {"v3_seals": 3, "v3_hashes": ["c" * 64, "b" * 64, "a" * 64], "c2_minted": 1808,
            "c2_total_checksum_count": 3160, "c2_total_checksum_root": "9" * 64, "c2_cas_records_hourly": 3154}
    out = p.run(_Stand(_counts_ok()))
    assert out["counts_before"] == out["counts_after"] == want
    assert out["v3_judged"] is True and out["counts_unchanged"] is True
    assert p.main(_Stand(_counts_ok())) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["counts_unchanged"] is True and len(printed["requests"]) == len(p.REQUESTS)

    # concordance-2: a move in any live field is a move; the hourly copy alone is not
    moves = [("a new concordance-2 record", lambda c2: c2["seals"]["total_checksum"].update(count=3161, root="8" * 64)),
             ("concordance-2's root alone", lambda c2: c2["seals"]["total_checksum"].update(root="8" * 64)),
             ("a new concordance-2 chain entry", lambda c2: c2["seals"].update(minted=1809))]
    for why, change in moves:
        out = p.run(_Stand(_moving(change)))
        assert out["counts_before"] != out["counts_after"] and out["counts_unchanged"] is False, why
    hourly = p.run(_Stand(_moving(lambda c2: c2["seals"].update(cas_records=3155))))
    assert (hourly["counts_before"]["c2_cas_records_hourly"], hourly["counts_after"]["c2_cas_records_hourly"]) == \
        (3154, 3155)
    assert hourly["counts_unchanged"] is True                       # the hourly copy is reported, not judged

    # V3 below its cap, ordered as V3 orders it: a new seal moves the count and the list, and is judged
    held = [("mathematics", _h("one")), ("real_estate", _h("two")), ("acoustics", _h("three"))]
    steady = p.run(_Stand(_V3Ledger(held).answers()))
    assert steady["counts_before"]["v3_seals"] == 3 and steady["counts_before"] == steady["counts_after"]
    assert steady["v3_judged"] is True and steady["counts_unchanged"] is True
    below = p.run(_Stand(_V3Ledger(held, seal_on_verify="mathematics").answers()))
    assert (below["counts_before"]["v3_seals"], below["counts_after"]["v3_seals"]) == (3, 4)
    assert below["counts_before"]["v3_hashes"] != below["counts_after"]["v3_hashes"]
    assert below["v3_judged"] is True and below["counts_unchanged"] is False
    swapped = _V3Ledger(held)

    def swap(method, url, body):                  # the list is judged too: same count, one listed hash replaced
        swapped.files[sorted(swapped.files)[0]] = _h("altered")
        return 200, "application/json", b'{"verdict": "HOLDS", "seal": null}'
    same_count = p.run(_Stand({**swapped.answers(), ORG + "/verify?seal=0": swap}))
    assert same_count["counts_before"]["v3_seals"] == same_count["counts_after"]["v3_seals"] == 3
    assert same_count["counts_before"]["v3_hashes"] != same_count["counts_after"]["v3_hashes"]
    assert same_count["v3_judged"] is True and same_count["counts_unchanged"] is False

    # V3 at its cap: a new mathematics seal names a file that sorts before 200 real_estate files, so it falls
    # outside the 200 listed and neither the count nor the list moves; V3 is not judged, and nothing passes
    full = [("real_estate", _h(f"estate {i}")) for i in range(200)]
    capped = p.run(_Stand(_V3Ledger(full, seal_on_verify="mathematics").answers()))
    assert capped["counts_before"] == capped["counts_after"]                       # the write is invisible here
    assert capped["counts_before"]["v3_seals"] == 200 and len(capped["counts_after"]["v3_hashes"]) == 200
    assert capped["v3_judged"] is False and capped["counts_unchanged"] is False
    at_cap = p.run(_Stand(_V3Ledger(full).answers()))
    assert at_cap["v3_judged"] is False and at_cap["counts_unchanged"] is False   # even with no write at all
    edge = p.run(_Stand(_V3Ledger(full[:199], seal_on_verify="real_estate").answers()))
    assert (edge["counts_before"]["v3_seals"], edge["counts_after"]["v3_seals"]) == (199, 200)
    assert edge["v3_judged"] is False and edge["counts_unchanged"] is False

    code, printed = _run_script(monkeypatch, capsys, _Net(_V3Ledger(held, seal_on_verify="mathematics").answers()))
    assert code == 1 and printed["v3_judged"] is True and printed["counts_unchanged"] is False
    code, printed = _run_script(monkeypatch, capsys, _Net(_V3Ledger(full).answers()))
    assert code == 1 and printed["v3_judged"] is False and printed["counts_unchanged"] is False

    unread = p.run(_Stand({V3_COUNT: (404, "application/json", b'{"count": 3}'),
                           C2_COUNT: urllib.error.URLError("down")}))
    assert unread["counts_before"] == unread["counts_after"] == dict.fromkeys(want)
    assert unread["v3_judged"] is False and unread["counts_unchanged"] is False
    odd = p.counts(_Stand({V3_COUNT: (200, "application/json", b'{"count": true, "seals": [{"content_hash": 1}, '
                                                                 b'"x", {"content_hash": "' + b"e" * 64 + b'"}]}'),
                           C2_COUNT: (200, "application/json", b'{"seals": {"minted": "1808", "cas_records": 3, '
                                                                 b'"total_checksum": {"root": 5, "count": 7}}}')}))
    assert odd == {"v3_seals": None, "v3_hashes": ["e" * 64], "c2_minted": None, "c2_total_checksum_count": 7,
                   "c2_total_checksum_root": None, "c2_cas_records_hourly": 3}
    no_hourly = {V3_COUNT: _counts_ok()[V3_COUNT],
                 C2_COUNT: (200, "application/json", b'{"seals": {"minted": 1, "total_checksum": {"root": "r", '
                                                     b'"count": 1}}}')}
    assert p.run(_Stand(no_hourly))["counts_unchanged"] is True       # an unread hourly copy does not judge either
