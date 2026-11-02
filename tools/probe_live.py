"""The live probe for run 2026-11-02-receipts-open: every live check of the run, as exact requests, and no seal.

    python tools/probe_live.py > probe.json        (the lead runs it; the tests never do)

Stdlib only. It makes exactly the requests in REQUESTS, between two reads of the seal counts (COUNTS), follows
no redirect (each answer is the answer to the request listed), and prints one JSON object. It exits 0 only
when counts_unchanged is true (see the end of this docstring), and 1 otherwise.

WHAT IT WRITES. Every request is a GET except exactly two POSTs:

    POST https://narrowhighway.org/verify?seal=0   {"claim": "1234+4321=5555"}
    POST https://narrowhighway.org/console         {"text": "how many ounces in a pound"}

POST /verify?seal=0 is a read. V3 seals a POST /verify by default, a permanent public receipt; ?seal=0 is what
keeps it a read (an earlier probe sent none and minted V3 seal eede51e6..., 2026-11-02). The claim is
distinctive, so a ledger entry that carried it would be found.

POST /console is NOT read-only. The Console asks the keeping's engine (its POST /ask), which writes a
conversation record on every run, and re-mints the unit seal that already exists for its answer,
fbb2ce1b13f54560d692174919273cfcb65843d0e8bf438802c141e8ac9f5577 ("1 pound = 16 ounces"), which adds no
ledger entry. The probe makes no new public seal. Every other request is strictly read-only.

For every request it reports:

    status    the HTTP status; when no answer came, "error" instead, naming what failed
    type      the content type, without its parameters
    bytes     the body's length in bytes
    sha256    the sha256 of the body as received, all 64 hex

and each derived field below, only on the requests it is defined for:

    body_names_hash     a request whose URL carries one of the sample hashes (HASHES): whether the body,
                        decoded as UTF-8 with undecodable bytes replaced, contains that hash's 64 hex characters
    record_sans_attest  a seal request (path /s/<hash>, or path /seal with ?hash=<hash>) answered 200 with a JSON
                        object: the sha256 (64 hex) of json.dumps(the object without its top-level "attest",
                        sort_keys=True, separators=(",", ":")) encoded as UTF-8. V3 re-signs "attest" on every
                        request, so the whole body varies while the record does not.
    seal_hashes         a /seals answer whose JSON "seals" is a list: the "content_hash" strings of its entries,
                        sorted
    sealed              a /verify answer: whether its JSON object carries a seal, i.e. a non-empty "seal" at the
                        top level or under "house" (where the two engines put one; CoreClient.seal_of reads the
                        same two places); None when the body is not a JSON object
    verdict             a /verify answer: the "verdict" of its JSON object; None when there is none
    says_16_ounces      a /console answer: whether the decoded body contains "16 ounces"
    version             a /capabilities answer: the "version" of its JSON object; None when there is none
    health              a /health answer: its JSON object, whole (small and public); None when not an object

And both engines' seal counts, read immediately before the requests and again after them (COUNTS):

    v3_seals                 "count" of GET https://narrowhighway.org/seals?limit=200: how many seals V3 lists
                             there, at most V3_CAP (200)
    v3_hashes                the "content_hash" strings that same answer lists, all of them, in the order V3
                             returns them. That order is not by time: V3's route sorts its ledger's file names,
                             keeps the last 200 and reverses them (Concordance-V3 http_api.py:294, ledger.py:59),
                             and a file is named for the seal's axis and hash prefix (receipts.py:152,
                             ledger.py:349).
    c2_minted               "seals"."minted" of GET https://narrowhighway.com/seals: concordance-2's ledger
                             chain, counted when asked
    c2_total_checksum_count  "seals"."total_checksum"."count" of the same answer: concordance-2's sealed records,
                             counted when asked
    c2_total_checksum_root   "seals"."total_checksum"."root" of the same answer: sha256 over every sealed
                             content hash, sorted; it changes if any seal is added
    c2_cas_records_hourly    "seals"."cas_records" of the same answer, copied from concordance-2's hourly
                             integrity check. It cannot see a write inside a run and can move across the hour,
                             so it is reported and NOT judged.

A field is None when it could not be read (no answer, not 200, not JSON, not the type named).

V3 is judged only below its cap. While V3 lists fewer than 200, its answer holds every entry its route draws
from, so a new one moves the count and the list. At 200 a new seal can fall outside the 200 it lists and leave
both unchanged, so there V3 cannot be judged. v3_judged is true only when V3's count was read both times and
was below 200 both times; otherwise V3 is reported not judged.

counts_unchanged is true only when V3 is judged and every judged field (all but c2_cas_records_hourly) was read
both times and none moved.
"""
from __future__ import annotations

import hashlib
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

ORG = "https://narrowhighway.org"
COM = "https://narrowhighway.com"
API = "https://api.narrowhighway.com"

C2_AFTER_AUGUST = "045bc6ffa8725277ddf45a65e256965641e6c9f0b7d761094e5286a85c359ad8"   # concordance-2's ledger
C2_BEFORE_AUGUST = "fcf98a9efde9758f21f26eb8d92281a2e5fc38a4c55c787b0577e507aa484745"  # concordance-2's ledger
V3_SEAL = "75cf60e58c6f5a2189c9c76d6235e95eea99676e10379ef22f8bfa9de194ac98"           # V3's ledger
PROFESSION = "786c40536bbc987b29ab74f85a38003a550ad14164a7d6ad73787922c926f2b9"        # a profession, concordance-2
UNHELD = "0" * 63 + "1"                                                                # held by neither engine
HASHES = (C2_AFTER_AUGUST, C2_BEFORE_AUGUST, V3_SEAL, PROFESSION, UNHELD)

VERIFY_CLAIM = "1234+4321=5555"
CONSOLE_TEXT = "how many ounces in a pound"
USER_AGENT = "witness-probe-live/1"


def _both_forms(host: str, h: str) -> List[Tuple[str, str, None]]:
    return [("GET", f"{host}/s/{h}", None), ("GET", f"{host}/seal?hash={h}", None)]


REQUESTS: List[Tuple[str, str, Optional[Dict[str, Any]]]] = [
    *_both_forms(ORG, C2_AFTER_AUGUST), *_both_forms(COM, C2_AFTER_AUGUST),
    *_both_forms(ORG, C2_BEFORE_AUGUST), *_both_forms(COM, C2_BEFORE_AUGUST),
    *_both_forms(ORG, V3_SEAL), *_both_forms(API, V3_SEAL),
    *_both_forms(ORG, PROFESSION), *_both_forms(COM, PROFESSION),
    *_both_forms(ORG, UNHELD),
    ("GET", f"{ORG}/find_verifier?q=speed+of+light", None),
    ("GET", f"{API}/find_verifier?q=speed+of+light", None),
    ("GET", f"{ORG}/audit.html", None),
    ("GET", f"{ORG}/seal.html", None),
    ("GET", f"{ORG}/proof.html", None),
    ("GET", f"{ORG}/find?q=speed+of+light", None),
    ("GET", f"{ORG}/book", None),
    ("GET", f"{ORG}/seals", None),
    ("GET", f"{ORG}/capabilities", None),
    ("GET", f"{ORG}/health", None),
    ("POST", f"{ORG}/verify?seal=0", {"claim": VERIFY_CLAIM}),
    ("POST", f"{ORG}/console", {"text": CONSOLE_TEXT}),
]

V3_COUNT_URL = f"{ORG}/seals?limit=200"
C2_COUNT_URL = f"{COM}/seals"
COUNTS = (V3_COUNT_URL, C2_COUNT_URL)   # GET, in this order, before REQUESTS and again after them

# (method, url, body) -> (status, content type, body bytes); raises when no answer comes
Transport = Callable[[str, str, Optional[Dict[str, Any]]], Tuple[int, str, bytes]]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse every redirect: the probe reports the answer to exactly the request it made (a 3xx comes back as
    its own status)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def http(method: str, url: str, body: Optional[Dict[str, Any]] = None,
         timeout: float = 40.0) -> Tuple[int, str, bytes]:
    """The real transport: one request, exactly as given, no redirect followed. An HTTP error status is an
    answer and is returned; no answer at all raises."""
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"User-Agent": USER_AGENT}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.build_opener(_NoRedirect).open(req, timeout=timeout) as r:
            return r.status, r.headers.get("content-type", ""), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("content-type", ""), e.read()


def _json_object(raw: bytes) -> Optional[Dict[str, Any]]:
    try:
        obj = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return obj if isinstance(obj, dict) else None


def derived(url: str, status: int, raw: bytes) -> Dict[str, Any]:
    """The derived fields defined in the module docstring, for one answer."""
    u = urllib.parse.urlsplit(url)
    path, query = u.path, urllib.parse.parse_qs(u.query)
    text = raw.decode("utf-8", "replace")
    obj = _json_object(raw)
    out: Dict[str, Any] = {}
    for h in HASHES:
        if h in url:
            out["body_names_hash"] = h in text
    if (path.startswith("/s/") or (path == "/seal" and "hash" in query)) and status == 200 and obj is not None:
        rec = {k: v for k, v in obj.items() if k != "attest"}
        out["record_sans_attest"] = hashlib.sha256(
            json.dumps(rec, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    if path == "/seals" and obj is not None and isinstance(obj.get("seals"), list):
        out["seal_hashes"] = sorted(e["content_hash"] for e in obj["seals"]
                                    if isinstance(e, dict) and isinstance(e.get("content_hash"), str))
    if path == "/verify":
        if obj is None:
            out["sealed"], out["verdict"] = None, None
        else:
            house = obj.get("house") if isinstance(obj.get("house"), dict) else {}
            out["sealed"] = bool(obj.get("seal")) or bool(house.get("seal"))
            out["verdict"] = obj.get("verdict")
    if path == "/console":
        out["says_16_ounces"] = "16 ounces" in text
    if path == "/capabilities":
        out["version"] = obj.get("version") if obj is not None else None
    if path == "/health":
        out["health"] = obj
    return out


def ask(transport: Transport, method: str, url: str, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """One request, reported: status, type, bytes, sha256 and the derived fields; or the error, when no
    answer came."""
    try:
        status, ctype, raw = transport(method, url, body)
    except Exception as e:  # noqa: BLE001 - no answer is a result to report, not a crash
        return {"error": f"{type(e).__name__}: {e}"}
    out: Dict[str, Any] = {"status": status, "type": (ctype or "").split(";")[0].strip(), "bytes": len(raw),
                           "sha256": hashlib.sha256(raw).hexdigest()}
    out.update(derived(url, status, raw))
    return out


def _int(v: Any) -> Optional[int]:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


UNJUDGED = ("c2_cas_records_hourly",)
V3_CAP = 200   # V3's /seals lists at most this many (Concordance-V3 http_api.py:293)


def counts(transport: Transport) -> Dict[str, Any]:
    """Both engines' seal counts, as the module docstring defines them."""
    out: Dict[str, Any] = {"v3_seals": None, "v3_hashes": None, "c2_minted": None, "c2_total_checksum_count": None,
                           "c2_total_checksum_root": None, "c2_cas_records_hourly": None}
    try:
        status, _t, raw = transport("GET", V3_COUNT_URL, None)
        v3 = (_json_object(raw) if status == 200 else None) or {}
        out["v3_seals"] = _int(v3.get("count"))
        if isinstance(v3.get("seals"), list):
            out["v3_hashes"] = [e["content_hash"] for e in v3["seals"]
                                if isinstance(e, dict) and isinstance(e.get("content_hash"), str)]
    except Exception:  # noqa: BLE001 - an unreadable count stays None
        pass
    try:
        status, _t, raw = transport("GET", C2_COUNT_URL, None)
        c2 = (_json_object(raw) if status == 200 else None) or {}
        seals = c2.get("seals") if isinstance(c2.get("seals"), dict) else {}
        total = seals.get("total_checksum") if isinstance(seals.get("total_checksum"), dict) else {}
        root = total.get("root")
        out["c2_minted"] = _int(seals.get("minted"))
        out["c2_total_checksum_count"] = _int(total.get("count"))
        out["c2_total_checksum_root"] = root if isinstance(root, str) else None
        out["c2_cas_records_hourly"] = _int(seals.get("cas_records"))
    except Exception:  # noqa: BLE001
        pass
    return out


def v3_judged(before: Dict[str, Any], after: Dict[str, Any]) -> bool:
    """True only when V3's count was read both times and was below V3_CAP both times."""
    return all(isinstance(c.get("v3_seals"), int) and c["v3_seals"] < V3_CAP for c in (before, after))


def unchanged(before: Dict[str, Any], after: Dict[str, Any]) -> bool:
    """True only when V3 is judged and every judged field was read both times and none moved."""
    judged = [k for k in before if k not in UNJUDGED]
    return v3_judged(before, after) and all(
        before[k] is not None and after.get(k) is not None and before[k] == after[k] for k in judged)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def run(transport: Transport = http) -> Dict[str, Any]:
    """The whole probe: the counts, every request in REQUESTS in order, the counts again."""
    started = _now()
    before = counts(transport)
    results = {f"{m} {u}": ask(transport, m, u, b) for m, u, b in REQUESTS}
    after = counts(transport)
    return {"probe": "witness tools/probe_live.py", "run": "2026-11-02-receipts-open",
            "started_at": started, "finished_at": _now(),
            "counts_before": before, "requests": results, "counts_after": after,
            "v3_judged": v3_judged(before, after), "counts_unchanged": unchanged(before, after)}


def main(transport: Transport = http) -> int:
    out = run(transport)
    print(json.dumps(out, indent=1))
    return 0 if out["counts_unchanged"] else 1


if __name__ == "__main__":
    sys.exit(main())
