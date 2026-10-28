"""python -m canon build <usfm_dir> <cross_references.txt>   build data/ from the public-domain WEB + openbible xrefs
   python -m canon synth <n> <out.jsonl> [--seed S]           n verified training trajectories
   python -m canon eval <examples.jsonl> --oracle|--scrambled  harness self-test (0 counterexamples / all caught)
   python -m canon serve [--port 8040]                         the four canon tools over HTTP (what a model calls)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"


def main(argv=None) -> int:
    a = list(sys.argv[1:] if argv is None else argv)
    if not a or a[0] in ("-h", "--help"):
        print(__doc__.strip()); return 0
    from .table import Table
    if a[0] == "build":
        t = Table.build(Path(a[1]), Path(a[2]) if len(a) > 2 else None)
        print(json.dumps(t.save(DATA), indent=1)); return 0
    t = Table.load(DATA)
    if a[0] == "synth":
        from . import synth
        seed = int(a[a.index("--seed") + 1]) if "--seed" in a else 0
        print(json.dumps(synth.write(t, Path(a[2]), int(a[1]), seed=seed), indent=1)); return 0
    if a[0] == "eval":
        from . import evaluate as E
        ex = [json.loads(l) for l in open(a[1], encoding="utf-8") if l.strip()]
        gen = E.scrambler_from(ex) if "--scrambled" in a else E.oracle_from(ex)
        r = E.evaluate(t, gen, ex)
        print(r["read"]); print(json.dumps({k: v for k, v in r.items() if k != "read"}, indent=1)); return 0
    if a[0] == "serve":
        from .serve import serve
        port = int(a[a.index("--port") + 1]) if "--port" in a else 8040
        serve(t, port=port); return 0
    print(__doc__.strip()); return 2


if __name__ == "__main__":
    raise SystemExit(main())
