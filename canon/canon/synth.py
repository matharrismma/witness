"""synth — training pairs for a model that looks up and cites, never recalls.

Every example is a trajectory: user question → tool call(s) → tool result (verbatim canon text) → answer
that quotes only what the tools returned, with references. The generator is template-driven and needs no
LLM; the canon and its cross-references supply all the content. A `draft` hook lets a model rewrite the
question or the prose of the answer — but every quote in every example is then re-checked by hash against
the canon and the example is DROPPED if any quote fails. The verifier is the filter; nothing enters the
training set unverified.

Task families (each a skill the model needs, none requiring text in its weights):
  lookup      "What does John 3:16 say?"               → read_passage → quote + ref
  locate      "Where is 'the Lord is my shepherd'?"    → find_text    → ref + quote
  xref        "What verses connect to Romans 5:8?"     → cross_refs → read_passage ×k → quotes + refs
  context     "Read John 3:14-18."                     → read_passage(range) → verses in order
  word        "Which verses in John use G25?"          → word_study → refs + quotes
  refuse      a question the canon cannot answer       → no tool, says so (no fabrication)
  correct     a misquote in the question               → find_text miss → nearest → the verbatim verse

Output: JSONL rows {"messages": [...], "tools": [...], "family": ..., "checked": {...}} in the chat/tool
format TRL's SFTTrainer and most chat templates accept.
"""
from __future__ import annotations

import json
import random
import re
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from .table import Table, normalise

TOOLS = [
    {"type": "function", "function": {"name": "read_passage", "description": "Verbatim verse text from the canon (WEB).",
     "parameters": {"type": "object", "properties": {"ref": {"type": "string", "description": "e.g. John 3:16 or John 3:14-18"}}, "required": ["ref"]}}},
    {"type": "function", "function": {"name": "find_text", "description": "Find the verse a quoted phrase belongs to; returns the verbatim verse or the nearest.",
     "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}}},
    {"type": "function", "function": {"name": "cross_refs", "description": "Recorded cross-references for a verse, most-voted first.",
     "parameters": {"type": "object", "properties": {"ref": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["ref"]}}},
    {"type": "function", "function": {"name": "word_study", "description": "Verses in a book tagged with a Strong's number.",
     "parameters": {"type": "object", "properties": {"strong": {"type": "string"}, "book": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["strong"]}}},
]

SYSTEM = ("You answer from the canon only. Use the tools to look verses up; quote them verbatim with their reference. "
          "If the canon does not answer the question, say so. Never recite scripture from memory.")


def _ref(r: Dict[str, Any]) -> str:
    return f"{r['book']} {r['chapter']}:{r['verse']}"


def _call(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    return {"role": "assistant", "content": None, "tool_calls": [{"type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


def _result(name: str, payload: Any) -> Dict[str, Any]:
    return {"role": "tool", "name": name, "content": json.dumps(payload, ensure_ascii=False)}


# ── the tools, executed against the table (this is also what the serving side exposes) ───────────
def run_tool(t: Table, name: str, args: Dict[str, Any]) -> Any:
    from .table import parse_ref
    if name == "read_passage":
        ref = str(args.get("ref", ""))
        m = re.match(r"^(.*?)\s+(\d+):(\d+)(?:-(\d+))?$", ref.strip())
        if not m:
            return {"error": f"could not parse {ref!r}"}
        base = parse_ref(f"{m.group(1)} {m.group(2)}:{m.group(3)}")
        if not base:
            return {"error": f"unknown book in {ref!r}"}
        end = int(m.group(4) or m.group(3))
        out = []
        for v in range(base[2], end + 1):
            r = t.get(base[0], base[1], v)
            if r:
                out.append({"ref": _ref(r), "text": r["text"], "key": r["key"]})
        return {"verses": out} if out else {"error": f"{ref} is not in the canon"}
    if name == "find_text":
        txt = str(args.get("text", ""))
        r = t.find_text(txt)
        if r:
            return {"match": "exact", "ref": _ref(r), "text": r["text"], "key": r["key"]}
        contain = t.find_phrase(txt)
        if len(contain) == 1:
            r = contain[0]
            return {"match": "contains", "ref": _ref(r), "text": r["text"], "key": r["key"]}
        if len(contain) > 1:
            return {"match": "ambiguous", "candidates": [{"ref": _ref(x), "text": x["text"]} for x in contain[:5]]}
        near, dist = t.nearest(txt)
        if near is None:
            return {"match": "none"}
        return {"match": "nearest", "ref": _ref(near), "text": near["text"], "key": near["key"], "distance": dist}
    if name == "cross_refs":
        base = parse_ref(str(args.get("ref", "")))
        if not base:
            return {"error": "could not parse ref"}
        return {"refs": [{"ref": f"{b} {c}:{v}", "votes": n} for b, c, v, n in t.xrefs(*base, limit=int(args.get("limit", 5)))]}
    if name == "word_study":
        strong = str(args.get("strong", "")).upper()
        book = args.get("book")
        hits = [h for h in t.with_strong(strong, limit=10_000) if not book or h[0] == book][: int(args.get("limit", 6))]
        return {"strong": strong, "verses": [{"ref": f"{b} {c}:{v}", "text": t.get(b, c, v)["text"]} for b, c, v in hits]}
    return {"error": f"unknown tool {name}"}


# ── families ──────────────────────────────────────────────────────────────────────────────────────
def _lookup(t: Table, rng: random.Random, r: Dict[str, Any]) -> Dict[str, Any]:
    q = rng.choice([f"What does {_ref(r)} say?", f"Read me {_ref(r)}.", f"Quote {_ref(r)}.", f"{_ref(r)}?",
                    f"Can you give me the text of {_ref(r)}?"])
    res = run_tool(t, "read_passage", {"ref": _ref(r)})
    ans = f"{_ref(r)} (WEB): {r['text']}"
    return {"family": "lookup", "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": q},
                                             _call("read_passage", {"ref": _ref(r)}), _result("read_passage", res),
                                             {"role": "assistant", "content": ans}]}


def _locate(t: Table, rng: random.Random, r: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    words = r["text"].split()
    if len(words) < 8:
        return None
    k = rng.randint(5, min(9, len(words) - 1))
    start = rng.randint(0, len(words) - k)
    phrase = " ".join(words[start:start + k]).strip(",.;:")
    q = rng.choice([f"Where is “{phrase}”?", f"Which verse says “{phrase}”?", f"Find the verse with the words “{phrase}”."])
    # the phrase is a fragment: find_text on a fragment returns nearest; the model must then read the verse
    res = run_tool(t, "find_text", {"text": phrase})
    if res.get("ref") != _ref(r):
        return None   # ambiguous fragment — skip rather than teach a wrong attribution
    ans = f"That is from {_ref(r)}.\n{_ref(r)} (WEB): {r['text']}"
    return {"family": "locate", "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": q},
                                             _call("find_text", {"text": phrase}), _result("find_text", res),
                                             {"role": "assistant", "content": ans}]}


def _xref(t: Table, rng: random.Random, r: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    xs = t.xrefs(r["book"], r["chapter"], r["verse"], limit=3)
    if len(xs) < 2:
        return None
    q = rng.choice([f"What other verses connect to {_ref(r)}?", f"Give me cross-references for {_ref(r)}.",
                    f"Which passages are related to {_ref(r)}?"])
    msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": q},
            _call("cross_refs", {"ref": _ref(r), "limit": 3}), _result("cross_refs", run_tool(t, "cross_refs", {"ref": _ref(r), "limit": 3}))]
    lines = []
    for b, c, v, n in xs:
        rr = t.get(b, c, v)
        msgs += [_call("read_passage", {"ref": f"{b} {c}:{v}"}), _result("read_passage", run_tool(t, "read_passage", {"ref": f"{b} {c}:{v}"}))]
        lines.append(f"- {b} {c}:{v}: {rr['text']}")
    msgs.append({"role": "assistant", "content": f"Cross-references recorded for {_ref(r)}:\n" + "\n".join(lines)})
    return {"family": "xref", "messages": msgs}


def _context(t: Table, rng: random.Random, r: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    n = rng.randint(2, 4)
    rows = [t.get(r["book"], r["chapter"], r["verse"] + i) for i in range(n)]
    if not all(rows):
        return None
    ref = f"{r['book']} {r['chapter']}:{r['verse']}-{r['verse'] + n - 1}"
    q = rng.choice([f"Read {ref}.", f"What do {ref} say?", f"Give me {ref} in order."])
    res = run_tool(t, "read_passage", {"ref": ref})
    ans = "\n".join(f"{_ref(x)}: {x['text']}" for x in rows)
    return {"family": "context", "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": q},
                                              _call("read_passage", {"ref": ref}), _result("read_passage", res),
                                              {"role": "assistant", "content": ans}]}


def _word(t: Table, rng: random.Random, r: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    strongs = [s for s in (r.get("strongs") or []) if len(t.with_strong(s, limit=3)) >= 2]
    if not strongs:
        return None
    s = rng.choice(strongs)
    hits = run_tool(t, "word_study", {"strong": s, "book": r["book"], "limit": 3})
    if len(hits["verses"]) < 2:
        return None
    q = rng.choice([f"Which verses in {r['book']} use Strong's {s}?", f"Show me {s} in {r['book']}.",
                    f"Where does {s} occur in {r['book']}?"])
    ans = f"Verses in {r['book']} tagged {s}:\n" + "\n".join(f"- {h['ref']}: {h['text']}" for h in hits["verses"])
    return {"family": "word", "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": q},
                                           _call("word_study", {"strong": s, "book": r["book"], "limit": 3}),
                                           _result("word_study", hits), {"role": "assistant", "content": ans}]}


_UNANSWERABLE = ["What did Moses eat for breakfast on the day he saw the burning bush?", "What is Paul's middle name?",
                 "Which verse mentions electricity?", "How tall was Goliath in centimetres?", "What colour were David's eyes?",
                 "Quote the 25th chapter of Jude.", "What does Hezekiah 3:5 say?", "Give me Psalm 151."]


def _refuse(t: Table, rng: random.Random, r: Dict[str, Any]) -> Dict[str, Any]:
    q = rng.choice(_UNANSWERABLE)
    msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": q}]
    m = re.search(r"([1-3]?\s?[A-Z][a-z]+)\s+(\d+)(?::(\d+))?", q)
    if m and ("Hezekiah" in q or "Psalm 151" in q or "Jude" in q):
        ref = f"{m.group(1)} {m.group(2)}:{m.group(3) or 1}"
        res = run_tool(t, "read_passage", {"ref": ref})
        msgs += [_call("read_passage", {"ref": ref}), _result("read_passage", res)]
        ans = f"The canon has no {ref}. I won't supply text that isn't there."
    else:
        ans = "The canon does not say. I won't guess or invent a verse for it."
    msgs.append({"role": "assistant", "content": ans})
    return {"family": "refuse", "messages": msgs}


def _correct(t: Table, rng: random.Random, r: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    words = r["text"].split()
    if len(words) < 6:
        return None
    i = rng.randrange(len(words))
    swap = rng.choice(["love", "light", "truth", "peace", "fear", "Lord", "people", "day", "earth", "heart"])
    wrong = " ".join(words[:i] + [swap] + words[i + 1:])
    q = rng.choice([f"Is it {_ref(r)} that says “{wrong}”?", f"I remember “{wrong}” — where is that?",
                    f"Check this quote for me: “{wrong}”"])
    res = run_tool(t, "find_text", {"text": wrong})
    if res.get("ref") != _ref(r):
        return None
    ans = (f"Not quite — that wording isn't in the canon. The verse is:\n{_ref(r)} (WEB): {r['text']}")
    return {"family": "correct", "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": q},
                                              _call("find_text", {"text": wrong}), _result("find_text", res),
                                              {"role": "assistant", "content": ans}]}


FAMILIES: Dict[str, Callable] = {"lookup": _lookup, "locate": _locate, "xref": _xref, "context": _context,
                                 "word": _word, "refuse": _refuse, "correct": _correct}
WEIGHTS = {"lookup": 3, "locate": 2, "xref": 2, "context": 2, "word": 1, "refuse": 1, "correct": 2}


# ── the filter: every quote in the answer must hash to the canon ─────────────────────────────────
_LINE = re.compile(r"^(?:- )?((?:[1-3] )?[A-Z][a-z]+(?: of [A-Z][a-z]+)?) (\d+):(\d+)(?: \(WEB\))?: (.+)$")


def check_example(t: Table, ex: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """True iff every cited line (`Ref (WEB): text` or `- Ref: text`) in every assistant turn is the verbatim
    verse at that reference, and an assistant turn with no cited line contains no verse-length text at all
    (a refusal must not smuggle a quote)."""
    from .table import parse_ref
    quotes = 0
    for m in ex["messages"]:
        if m["role"] != "assistant" or not m.get("content"):
            continue
        for line in m["content"].splitlines():
            lm = _LINE.match(line.strip())
            if lm:
                quotes += 1
                pr = parse_ref(f"{lm.group(1)} {lm.group(2)}:{lm.group(3)}")
                hit = t.find_text(lm.group(4))
                if hit is None:
                    return False, {"quotes": quotes, "failed": line[:80], "reason": "not verbatim"}
                if not pr or pr != (hit["book"], hit["chapter"], hit["verse"]):
                    return False, {"quotes": quotes, "failed": line[:80], "reason": f"attributed to {pr}, is {_ref(hit)}"}
            else:
                # prose line: must not itself be (or contain) a verse — scripture only ever appears cited
                if len(line.split()) >= 6 and (t.find_text(line) or t.verses_in(line)):
                    return False, {"quotes": quotes, "failed": line[:80], "reason": "uncited scripture in prose"}
    return True, {"quotes": quotes}


def generate(t: Table, n: int, *, seed: int = 0, draft: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
             families: Optional[Dict[str, int]] = None) -> Iterator[Dict[str, Any]]:
    """Yield n verified examples. `draft`, if given, may rewrite an example (e.g. an LLM paraphrasing the
    question or the answer's prose); whatever it returns is re-checked and dropped on any failure."""
    rng = random.Random(seed)
    weights = families or WEIGHTS
    names = list(weights)
    wts = [weights[k] for k in names]
    made = dropped = 0
    rows = t.rows
    while made < n:
        fam = rng.choices(names, wts)[0]
        r = rng.choice(rows)
        ex = FAMILIES[fam](t, rng, r)
        if ex is None:
            continue
        if draft is not None:
            ex = draft(ex) or ex
        ok, info = check_example(t, ex)
        if not ok:
            dropped += 1
            continue
        ex["checked"] = info
        ex["tools"] = TOOLS
        made += 1
        yield ex
    generate.dropped = dropped  # type: ignore[attr-defined]


def write(t: Table, path: Path, n: int, **kw) -> Dict[str, Any]:
    fam_counts: Dict[str, int] = {}
    with open(path, "w", encoding="utf-8") as f:
        for ex in generate(t, n, **kw):
            fam_counts[ex["family"]] = fam_counts.get(ex["family"], 0) + 1
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")
    return {"written": n, "dropped": getattr(generate, "dropped", 0), "families": fam_counts, "path": str(path)}


__all__ = ["generate", "write", "check_example", "run_tool", "TOOLS", "SYSTEM", "FAMILIES"]
