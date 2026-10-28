"""verifier — the scripture domain as a Concordance verifier plugin.

Registered through the `concordance.verifiers` entry-point group, so the core engine verifies scripture
without carrying any of it: `verify(steps=[{"domain": "scripture", "spec": {"SCRIPTURE_VERIFY": {...}}}])`.

    SCRIPTURE_VERIFY packet (any subset):
      quote            a quoted verse (or verses) — checked by hash against the canon
      ref              a reference the quote is attributed to ("John 3:16")
      claimed_ref      a bare reference claim ("the verse says X" → does X live at this ref?)
      claimed_strong   {"ref": ..., "number": "G25"} — does this Strong's number occur in that verse?
      claimed_xref     {"from": "John 3:16", "to": "Romans 5:8"} — is this a recorded cross-reference?

Checks are exact: the canon is the pure stratum. A quote that misses is a counterexample naming the nearest
verse and the token distance, so the writer learns what it changed. Never generates text.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .table import Table, normalise, parse_ref

try:  # the engine's result types; a plain fallback keeps this importable without the engine
    from concordance.verifiers.base import VerifierResult, confirm, dispatch, error, mismatch, na
except Exception:  # noqa: BLE001
    VerifierResult = dict  # type: ignore

    def confirm(name, detail="", data=None): return {"name": name, "status": "CONFIRMED", "detail": detail, "data": data or {}}
    def mismatch(name, detail, data=None): return {"name": name, "status": "MISMATCH", "detail": detail, "data": data or {}}
    def error(name, detail, data=None): return {"name": name, "status": "ERROR", "detail": detail, "data": data or {}}
    def na(name, reason="no artifact provided", data=None): return {"name": name, "status": "NOT_APPLICABLE", "detail": reason, "data": data or {}}
    def dispatch(packet, key, rules, *, domain, none_reason=""):
        art = packet.get(key) or {}
        out = [fn(art) for req, fn in rules if (req(art) if callable(req) else all(k in art for k in req))]
        return out or [na(domain, none_reason)]

_D = "scripture"
ARTIFACT_KEY = "SCRIPTURE_VERIFY"
STRATUM = "pure"            # checked by hash against the canon: exact, no tolerance — the engine reads this
_TABLE: Optional[Table] = None


def table() -> Table:
    global _TABLE
    if _TABLE is None:
        d = Path(os.environ.get("CANON_DATA_DIR", "") or Path(__file__).resolve().parents[1] / "data")
        _TABLE = Table.load(d)
    return _TABLE


def _ref_tuple(ref: Any):
    if isinstance(ref, (list, tuple)) and len(ref) == 3:
        return (str(ref[0]), int(ref[1]), int(ref[2]))
    return parse_ref(str(ref or ""))


def _split_quote(q: str) -> List[str]:
    """A quote may span verses; try the whole, then verse-sized pieces split on sentence ends."""
    return [q] + [s for s in re.split(r"(?<=[.!?;])\s+", q) if len(s.split()) >= 4]


def verify_quote(spec: Dict[str, Any]) -> VerifierResult:
    """The quote hashes to a verse in the canon (exact after normalisation). With `ref`, it must hash to
    THAT verse; a miss names the nearest verse and the token distance — the counterexample."""
    name = f"{_D}.quote"
    q = str(spec.get("quote") or "").strip()
    if not q:
        return na(name, "no quote to check")
    t = table()
    ref = _ref_tuple(spec.get("ref")) if spec.get("ref") else None
    if spec.get("ref") and not ref:
        return error(name, f"could not parse ref {spec.get('ref')!r}")
    hit = t.find_text(q)
    if hit is None:
        # a multi-verse quote: every verse-sized piece must hit, in order
        pieces = _split_quote(q)[1:]
        hits = [t.find_text(p) for p in pieces]
        if pieces and all(hits):
            refs = [(h["book"], h["chapter"], h["verse"]) for h in hits]
            ok_order = all(refs[i][0] == refs[i + 1][0] and (refs[i][1], refs[i][2]) < (refs[i + 1][1], refs[i + 1][2]) for i in range(len(refs) - 1))
            data = {"verses": [f"{b} {c}:{v}" for b, c, v in refs], "keys": [h["key"] for h in hits], "exact": True}
            if ref and refs[0] != ref:
                return mismatch(name, f"quote is {refs[0][0]} {refs[0][1]}:{refs[0][2]}ff, attributed to {ref[0]} {ref[1]}:{ref[2]}",
                                dict(data, counterexample={"what": "ref", "claimed": f"{ref[0]} {ref[1]}:{ref[2]}", "recomputed": data["verses"][0]}))
            return confirm(name, f"{len(hits)} verses verbatim, {'in order' if ok_order else 'OUT OF ORDER'}: {', '.join(data['verses'])}", data) \
                if ok_order else mismatch(name, "verses verbatim but out of canonical order: " + ", ".join(data["verses"]), data)
        near, dist = t.nearest(q, within=ref)
        if near is None:
            return mismatch(name, "quote matches no verse in the canon and no neighbour is close",
                            {"counterexample": {"what": "quote", "claimed": q[:200], "recomputed": None, "off_by": None}})
        nref = f"{near['book']} {near['chapter']}:{near['verse']}"
        return mismatch(name, f"quote is not verbatim; nearest is {nref} at {dist} word edit{'s' if dist != 1 else ''}",
                        {"nearest": nref, "nearest_text": near["text"], "distance": dist,
                         "counterexample": {"what": "quote", "claimed": q[:200], "recomputed": near["text"][:200],
                                            "off_by": dist, "nearest": nref}})
    hr = (hit["book"], hit["chapter"], hit["verse"])
    data = {"verse": f"{hr[0]} {hr[1]}:{hr[2]}", "key": hit["key"], "exact": True}
    if ref and hr != ref:
        return mismatch(name, f"quote is {data['verse']} but attributed to {ref[0]} {ref[1]}:{ref[2]}",
                        dict(data, counterexample={"what": "ref", "claimed": f"{ref[0]} {ref[1]}:{ref[2]}", "recomputed": data["verse"], "off_by": None}))
    return confirm(name, f"verbatim {data['verse']} ({t.translation}); key {hit['key'][:12]}…", data)


def verify_ref(spec: Dict[str, Any]) -> VerifierResult:
    """A bare reference resolves to a verse that exists."""
    name = f"{_D}.ref"
    raw = spec.get("claimed_ref")
    if raw is None:
        return na(name)
    ref = _ref_tuple(raw)
    if not ref:
        return mismatch(name, f"{raw!r} is not a reference the canon recognises",
                        {"counterexample": {"what": "ref", "claimed": str(raw), "recomputed": None}})
    row = table().get(*ref)
    if row is None:
        return mismatch(name, f"{ref[0]} {ref[1]}:{ref[2]} does not exist in the canon",
                        {"counterexample": {"what": "ref", "claimed": f"{ref[0]} {ref[1]}:{ref[2]}", "recomputed": None}})
    return confirm(name, f"{ref[0]} {ref[1]}:{ref[2]} exists; key {row['key'][:12]}…", {"verse": f"{ref[0]} {ref[1]}:{ref[2]}", "key": row["key"], "text": row["text"]})


def verify_strong(spec: Dict[str, Any]) -> VerifierResult:
    name = f"{_D}.strong"
    c = spec.get("claimed_strong")
    if not isinstance(c, dict):
        return na(name)
    ref = _ref_tuple(c.get("ref"))
    num = str(c.get("number") or "").upper()
    if not ref or not num:
        return error(name, "claimed_strong needs ref and number")
    row = table().get(*ref)
    if row is None:
        return mismatch(name, f"{ref[0]} {ref[1]}:{ref[2]} does not exist")
    present = num in (row.get("strongs") or [])
    data = {"verse": f"{ref[0]} {ref[1]}:{ref[2]}", "number": num, "strongs_in_verse": sorted(set(row.get("strongs") or []))}
    if present:
        return confirm(name, f"{num} occurs in {data['verse']}", data)
    return mismatch(name, f"{num} does not occur in {data['verse']} (tagged: {', '.join(data['strongs_in_verse'][:12])})",
                    dict(data, counterexample={"what": "strong", "claimed": num, "recomputed": data["strongs_in_verse"]}))


def verify_xref(spec: Dict[str, Any]) -> VerifierResult:
    name = f"{_D}.xref"
    c = spec.get("claimed_xref")
    if not isinstance(c, dict):
        return na(name)
    a, b = _ref_tuple(c.get("from")), _ref_tuple(c.get("to"))
    if not a or not b:
        return error(name, "claimed_xref needs from and to")
    lst = table().xrefs(*a, limit=10_000)
    for tb, tc, tv, votes in lst:
        if (tb, tc, tv) == b:
            return confirm(name, f"{a[0]} {a[1]}:{a[2]} → {b[0]} {b[1]}:{b[2]} is recorded ({votes} votes)",
                           {"from": f"{a[0]} {a[1]}:{a[2]}", "to": f"{b[0]} {b[1]}:{b[2]}", "votes": votes})
    return mismatch(name, f"{a[0]} {a[1]}:{a[2]} → {b[0]} {b[1]}:{b[2]} is not a recorded cross-reference",
                    {"counterexample": {"what": "xref", "claimed": f"{b[0]} {b[1]}:{b[2]}",
                                        "recomputed": [f"{tb} {tc}:{tv}" for tb, tc, tv, _ in lst[:5]]}})


_RULES = [
    (("quote",), verify_quote),
    (("claimed_ref",), verify_ref),
    (("claimed_strong",), verify_strong),
    (("claimed_xref",), verify_xref),
]


def run(packet: Dict[str, Any]) -> List[VerifierResult]:
    return dispatch(packet, "SCRIPTURE_VERIFY", _RULES, domain="scripture", none_reason="no SCRIPTURE_VERIFY artifacts present")


__all__ = ["run", "verify_quote", "verify_ref", "verify_strong", "verify_xref", "table", "ARTIFACT_KEY"]
