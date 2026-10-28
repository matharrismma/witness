"""evaluate — the inverted eval: not "does it sound biblical", but how often it is caught.

Runs a model over held-out questions, executing its tool calls against the canon, then checks every cited
line by hash and every prose line for smuggled scripture. Reports, per task family and overall:

    cited          lines the model presented as scripture
    verbatim       of those, hash hits at the stated reference
    counterexamples  misquotes, misattributions, uncited scripture, answers with no retrieval
    posterior      Beta(1 + failures, 1 + successes): the probability the NEXT citation is wrong — mean and
                   95% upper bound — so a small eval reports honest uncertainty instead of a point score

The model is any callable `generate(messages, tools) -> assistant message dict` (content and/or tool_calls);
`loop()` drives the tool round-trips. A `--dry` run uses a perfect oracle (the generator's own answers) to
prove the harness scores 0 counterexamples on verified data, and a `--scrambled` run proves it catches them.
"""
from __future__ import annotations

import json
import math
import random
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .synth import TOOLS, _LINE, run_tool
from .table import Table, parse_ref

Generate = Callable[[List[Dict[str, Any]], List[Dict[str, Any]]], Dict[str, Any]]


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta (Lentz)."""
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / (c if abs(c) > tiny else tiny)
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / (c if abs(c) > tiny else tiny)
        de = d * c
        h *= de
        if abs(de - 1.0) < 3e-14:
            break
    return h


def betainc(a: float, b: float, x: float) -> float:
    """Regularised incomplete beta I_x(a, b) — the Beta CDF. No scipy."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lbt = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x)
    if x < (a + 1) / (a + b + 2):
        return math.exp(lbt) * _betacf(a, b, x) / a
    return 1.0 - math.exp(lbt) * _betacf(b, a, 1 - x) / b


def beta_posterior(failures: int, successes: int) -> Dict[str, float]:
    """Beta(1+f, 1+s) on the failure rate: posterior mean and the 95% upper bound (by bisection on the CDF)."""
    a, b = 1 + failures, 1 + successes
    lo, hi = 0.0, 1.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if betainc(a, b, mid) < 0.95:
            lo = mid
        else:
            hi = mid
    return {"mean": a / (a + b), "upper95": hi, "failures": failures, "successes": successes}


def loop(t: Table, generate: Generate, messages: List[Dict[str, Any]], max_turns: int = 8) -> List[Dict[str, Any]]:
    """Drive the model: execute its tool calls against the canon until it answers in prose."""
    msgs = list(messages)
    for _ in range(max_turns):
        out = generate(msgs, TOOLS)
        msgs.append(out)
        calls = out.get("tool_calls") or []
        if not calls:
            return msgs
        for c in calls:
            fn = c["function"]
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            msgs.append({"role": "tool", "name": fn["name"], "content": json.dumps(run_tool(t, fn["name"], args), ensure_ascii=False)})
    return msgs


def judge(t: Table, msgs: List[Dict[str, Any]], expected_family: str) -> Dict[str, Any]:
    """Score one finished conversation. Every counterexample is named with its kind."""
    cited = verbatim = 0
    cx: List[Dict[str, Any]] = []
    retrieved = any(m.get("role") == "tool" for m in msgs)
    final = next((m for m in reversed(msgs) if m.get("role") == "assistant" and m.get("content")), None)
    if final is None:
        return {"cited": 0, "verbatim": 0, "counterexamples": [{"kind": "no_answer"}], "retrieved": retrieved}
    for line in final["content"].splitlines():
        lm = _LINE.match(line.strip())
        if lm:
            cited += 1
            pr = parse_ref(f"{lm.group(1)} {lm.group(2)}:{lm.group(3)}")
            hit = t.find_text(lm.group(4))
            if hit is None:
                near, dist = t.nearest(lm.group(4), within=pr)
                cx.append({"kind": "misquote", "line": line[:120], "nearest": f"{near['book']} {near['chapter']}:{near['verse']}" if near else None, "distance": dist})
            elif not pr or pr != (hit["book"], hit["chapter"], hit["verse"]):
                cx.append({"kind": "misattribution", "line": line[:120], "is": f"{hit['book']} {hit['chapter']}:{hit['verse']}"})
            else:
                verbatim += 1
        elif len(line.split()) >= 6 and (t.find_text(line) or t.verses_in(line)):
            cx.append({"kind": "uncited_scripture", "line": line[:120]})
    if cited and not retrieved:
        cx.append({"kind": "cited_without_retrieval"})
    if expected_family == "refuse" and cited:
        cx.append({"kind": "answered_unanswerable"})
    if expected_family != "refuse" and cited == 0 and not cx:
        cx.append({"kind": "no_citation"})
    return {"cited": cited, "verbatim": verbatim, "counterexamples": cx, "retrieved": retrieved}


def evaluate(t: Table, generate: Generate, examples: List[Dict[str, Any]]) -> Dict[str, Any]:
    per: Dict[str, Dict[str, int]] = {}
    kinds: Dict[str, int] = {}
    total = {"n": 0, "cited": 0, "verbatim": 0, "counterexamples": 0, "clean": 0}
    for ex in examples:
        fam = ex.get("family", "?")
        prompt = [m for m in ex["messages"] if m["role"] in ("system", "user")][:2]
        msgs = loop(t, generate, prompt)
        j = judge(t, msgs, fam)
        p = per.setdefault(fam, {"n": 0, "cited": 0, "verbatim": 0, "counterexamples": 0, "clean": 0})
        for d in (p, total):
            d["n"] += 1
            d["cited"] += j["cited"]
            d["verbatim"] += j["verbatim"]
            d["counterexamples"] += len(j["counterexamples"])
            d["clean"] += int(not j["counterexamples"])
        for c in j["counterexamples"]:
            kinds[c["kind"]] = kinds.get(c["kind"], 0) + 1
    def post(d):
        return beta_posterior(d["n"] - d["clean"], d["clean"])
    return {"total": {**total, "posterior_fail_rate": post(total)},
            "families": {k: {**v, "posterior_fail_rate": post(v)} for k, v in per.items()},
            "counterexample_kinds": kinds,
            "read": (f"{total['clean']}/{total['n']} conversations clean; posterior P(next conversation has a "
                     f"counterexample) mean {post(total)['mean']:.1%}, 95% upper {post(total)['upper95']:.1%}; "
                     f"{total['verbatim']}/{total['cited']} cited lines verbatim at their reference")}


# ── two reference generators: the oracle and the scrambler ────────────────────────────────────────
def oracle_from(examples: List[Dict[str, Any]]) -> Generate:
    """Replays the verified example's own assistant turns — must score 0 counterexamples. Duplicate questions
    are served in order (a queue per question), and a conversation's turn index is read from the transcript
    itself, so the oracle is stateless across conversations."""
    from collections import deque
    by_user: Dict[str, deque] = {}
    for ex in examples:
        user = next(m["content"] for m in ex["messages"] if m["role"] == "user")
        by_user.setdefault(user, deque()).append([m for m in ex["messages"] if m["role"] == "assistant"])
    current: Dict[str, List[Dict[str, Any]]] = {}

    def gen(msgs, tools):
        user = next(m["content"] for m in msgs if m["role"] == "user")
        i = sum(1 for m in msgs if m.get("role") == "assistant")
        if i == 0:   # a fresh conversation: take the next recorded trajectory for this question
            q = by_user.get(user)
            current[user] = q.popleft() if q else [{"role": "assistant", "content": "The canon does not say."}]
            if q is not None and not q:
                q.append(current[user])   # keep the last one for any re-asks
        turns = current.get(user) or [{"role": "assistant", "content": "The canon does not say."}]
        return turns[min(i, len(turns) - 1)]
    return gen


def scrambler_from(examples: List[Dict[str, Any]], seed: int = 0) -> Generate:
    """The oracle with one word changed in each cited line — must be caught every time."""
    rng = random.Random(seed)
    base = oracle_from(examples)

    def gen(msgs, tools):
        out = dict(base(msgs, tools))
        if out.get("content"):
            lines = []
            for line in out["content"].splitlines():
                m = _LINE.match(line.strip())
                if m:
                    words = m.group(4).split()
                    k = rng.randrange(len(words))
                    words[k] = "mercy"
                    line = f"{m.group(1)} {m.group(2)}:{m.group(3)} (WEB): {' '.join(words)}"
                lines.append(line)
            out["content"] = "\n".join(lines)
        return out
    return gen


__all__ = ["evaluate", "judge", "loop", "beta_posterior", "betainc", "oracle_from", "scrambler_from"]
