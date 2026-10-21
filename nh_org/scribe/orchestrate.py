"""Scribe loop orchestrator — the .org app's first tool.

strip context -> packets -> CORE engine -> SVD -> feedback -> (next pass) -> reapply context -> seal.

Five writers draft a memo and its claims by hand (no tools). Consensus is not truth: the writers
can agree to 5-6 significant figures and still be wrong together. The datum is the core engine's
deterministic recompute of each claim (nh_org.core_client -> POST /verify). The SVD over the claim
matrix is a SPEC-AMBIGUITY detector — it shows where the writers diverged, i.e. where the spec was
readable two ways — never a truth signal. The verified center draft is sealed through the core;
the receipt lives at narrowhighway.org/s/<hash>.

This module imports NO core code. Every verdict and every seal comes over HTTP from the core.

CLI:
  python -m nh_org.scribe.orchestrate pass N [--root DIR]      # score a pass, write report + feedback
  python -m nh_org.scribe.orchestrate final N [--root DIR]     # seal the center draft (add --seal to WRITE)
  python -m nh_org.scribe.orchestrate fb N AGENT [--root DIR]  # the per-writer feedback sheet
"""
from __future__ import annotations

import glob
import json
import os
import sys
from typing import Dict, Optional

from ..core_client import CoreClient, CoreUnavailable
from .packets import CLAIMS, packets_for

# Context the writers never saw. Re-applied only to the final, verified draft.
CONTEXT = {"[AUTHORITY]": "Northwest Georgia Joint Development Authority",
           "[COMPANY]": "Example Manufacturing Co.",
           "[PROJECT]": "Plant 2 expansion",
           "[COUNTY]": "Walker County"}


def _root(root: Optional[str]) -> str:
    return root or os.environ.get("SCRIBE_ROOT") or os.getcwd()


# ── the engine, over the wire ──────────────────────────────────────────────────────────────────
def verify_claim(cid, value, formula, client: CoreClient) -> Dict[str, object]:
    """Send one writer claim's step(s) to the core and read the verdicts back."""
    out = {"recompute": None, "arith": None, "detail": ""}
    for st in packets_for(cid, value, formula):
        res = client.verify([st])
        tr = (res.get("trail") or [{}])[0]
        key = "recompute" if st["id"] == "re" else "arith"
        out[key] = tr.get("status")
        out["detail"] += f"[{key}:{tr.get('status')}] {tr.get('detail', '')}  "
    return out


# ── scoring a pass (SVD = spec-ambiguity detector) ───────────────────────────────────────────────
def load_pass(n, root=None):
    agents = {}
    for f in sorted(glob.glob(f"{_root(root)}/passes/pass{n}/agent*.json")):
        name = os.path.basename(f)[:-5]
        try:
            agents[name] = json.load(open(f, encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            agents[name] = {"error": str(e)}
    return agents


def score(n, root=None, client: Optional[CoreClient] = None):
    import numpy as np  # the SVD lives in the .org app; the core stays stdlib-only
    client = client or CoreClient()
    root = _root(root)
    agents = load_pass(n, root)
    names = list(agents)
    M = np.full((len(names), len(CLAIMS)), np.nan)
    verdicts = {}
    for i, a in enumerate(names):
        claims = {c.get("id"): c for c in agents[a].get("claims", []) if isinstance(c, dict)}
        verdicts[a] = {}
        for j, cid in enumerate(CLAIMS):
            c = claims.get(cid)
            if not c or not isinstance(c.get("value"), (int, float)):
                verdicts[a][cid] = {"recompute": "MISSING", "arith": None, "detail": "no packet"}
                continue
            M[i, j] = float(c["value"])
            verdicts[a][cid] = verify_claim(cid, c["value"], c.get("formula", ""), client)

    med = np.nanmedian(M, axis=0)
    R = M / med
    R = np.where(np.isnan(R), 1.0, R)
    C = R - R.mean(axis=0)
    U, S, Vt = np.linalg.svd(C, full_matrices=False)
    spread = float(np.sqrt((C ** 2).sum() / max(1, len(names))))
    share = float(S[0] ** 2 / max(1e-12, (S ** 2).sum()))
    axis = [(CLAIMS[j], float(Vt[0, j])) for j in np.argsort(-np.abs(Vt[0]))[:4]]

    broken = {a: [cid for cid in CLAIMS if verdicts[a][cid]["recompute"] in ("MISMATCH", "MISSING", "ERROR")]
              for a in names}
    dist = {a: float(np.linalg.norm(C[i])) for i, a in enumerate(names)}
    clean = [a for a in names if not broken[a]]
    center = min(clean or names, key=lambda a: dist[a])

    divergent = {}
    for j, cid in enumerate(CLAIMS):
        col = M[:, j]
        if np.nanmax(col) > 0 and (np.nanmax(col) - np.nanmin(col)) / abs(np.nanmedian(col) or 1) > 1e-3:
            divergent[cid] = {a: (None if np.isnan(M[i, j]) else M[i, j]) for i, a in enumerate(names)}

    report = {"pass": n, "agents": names, "spread": spread, "singular_values": [float(x) for x in S],
              "top_axis_share": share, "top_axis_claims": axis, "broken": broken,
              "broken_total": sum(len(v) for v in broken.values()), "distance_to_center": dist,
              "center_draft": center, "divergent": divergent, "verdicts": verdicts,
              "matrix": {a: {cid: (None if np.isnan(M[i, j]) else M[i, j]) for j, cid in enumerate(CLAIMS)}
                         for i, a in enumerate(names)}}
    d = f"{root}/passes/pass{n}"
    os.makedirs(d, exist_ok=True)
    json.dump(report, open(f"{d}/report.json", "w", encoding="utf-8"), indent=1)
    open(f"{d}/feedback.md", "w", encoding="utf-8").write(feedback(report))
    return report


def feedback(rep):
    L = [f"# Feedback after pass {rep['pass']}", ""]
    L.append(f"Spread {rep['spread']:.4f}; top disagreement axis carries {rep['top_axis_share']:.0%} of the "
             f"variance and loads on: " + ", ".join(f"{c} ({w:+.2f})" for c, w in rep["top_axis_claims"]) + ".")
    L.append("")
    L.append("## Engine verdicts on YOUR claims (deterministic recompute from the spec inputs)")
    L.append("{PER_AGENT}")
    L.append("")
    L.append("## Where the writers diverge (values only; no names)")
    for cid, vals in rep["divergent"].items():
        vs = sorted(v for v in vals.values() if v is not None)
        L.append(f"- {cid}: {', '.join(f'{v:,.4g}' for v in vs)}")
    L.append("")
    L.append("Resolve every MISMATCH and every divergent claim. Re-read the spec sentence that governs it. "
             "Return the full JSON again (draft + all claims).")
    return "\n".join(L)


def per_agent_feedback(rep, agent, root=None):
    rows = []
    for cid in CLAIMS:
        v = rep["verdicts"][agent][cid]
        rows.append(f"- {cid}: {v['recompute']}" + (f" — {v['detail'].strip()}" if v["recompute"] != "CONFIRMED" else ""))
    base = open(f"{_root(root)}/passes/pass{rep['pass']}/feedback.md", encoding="utf-8").read()
    return base.replace("{PER_AGENT}", "\n".join(rows))


# ── final: reapply context, seal through the core, ledger ────────────────────────────────────────
def final(n, root=None, client: Optional[CoreClient] = None, seal=False):
    client = client or CoreClient()
    root = _root(root)
    rep = json.load(open(f"{root}/passes/pass{n}/report.json", encoding="utf-8"))
    a = rep["center_draft"]
    draft = load_pass(n, root)[a]["draft"]
    for k, v in CONTEXT.items():
        draft = draft.replace(k, v)
    steps = []
    for c in load_pass(n, root)[a]["claims"]:
        for st in packets_for(c["id"], c["value"], c.get("formula", "")):
            if st["id"] == "re":
                steps.append(dict(st, id=c["id"]))
    res = client.verify(steps, seal=seal)
    sealc = CoreClient.seal_of(res)
    ledger = {"pass": n, "center_draft": a, "verdict": res.get("verdict"), "seal": sealc, "sealed": bool(seal),
              "passes": [json.load(open(f, encoding="utf-8"))["spread"]
                         for f in sorted(glob.glob(f"{root}/passes/pass*/report.json"))],
              "broken_by_pass": [json.load(open(f, encoding="utf-8"))["broken_total"]
                                 for f in sorted(glob.glob(f"{root}/passes/pass*/report.json"))]}
    open(f"{root}/ledger.jsonl", "a", encoding="utf-8").write(json.dumps(ledger) + "\n")
    tag = "Seal" if seal else "Verdict (dry-run, not sealed; pass --seal to mint the receipt)"
    open(f"{root}/final_memo.md", "w", encoding="utf-8").write(
        draft + f"\n\n---\n{tag}: " + json.dumps(sealc or {"verdict": res.get("verdict")}) + "\n")
    return ledger, draft


def _main(argv):
    if not argv:
        print(__doc__)
        return 2
    cmd = argv[0]
    root = None
    if "--root" in argv:
        root = argv[argv.index("--root") + 1]
    seal = "--seal" in argv
    try:
        if cmd == "pass":
            rep = score(int(argv[1]), root)
            print(json.dumps({k: rep[k] for k in ("spread", "singular_values", "top_axis_share",
                  "top_axis_claims", "broken", "broken_total", "center_draft", "distance_to_center")}, indent=1))
        elif cmd == "final":
            ledger, draft = final(int(argv[1]), root, seal=seal)
            print(json.dumps(ledger, indent=1))
            print("\n" + draft)
        elif cmd == "fb":
            rep = json.load(open(f"{_root(root)}/passes/pass{int(argv[1])}/report.json", encoding="utf-8"))
            print(per_agent_feedback(rep, argv[2], root))
        else:
            print(__doc__)
            return 2
    except CoreUnavailable as e:
        print(f"core unavailable — no verdict fabricated: {e}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
