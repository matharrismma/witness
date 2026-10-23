# witness

The **witness, record and experience layer** of Narrow Highway — the `.org` side, split out from
the core engine in V3 (2026-10-20).

This is an **application**. It holds surfaces and orchestration and calls the Narrow Highway **core
engine** over HTTP for every verification and every seal. It never imports the core, holds no
verifier and no corpus of its own. One engine, one corpus, two surfaces:

- **narrowhighway.com** — the v2 app engine (the library, the corpus, the Console's doors). A separate repo.
- **Concordance-V3** — the verification engine: `/verify`, `/s/<hash>`, `/scribe`, packet schemas. The
  receipts the record shows are minted there (`NH_VERIFY_URL`).
- **narrowhighway.org** — this app (the record, the witness, the Console, the Scribe). Calls the core.

The one link to the core is [`nh_org/core_client.py`](nh_org/core_client.py): a stdlib HTTP client
that posts to the core's public `POST /verify` door (`?seal=0` read-only, `?seal=1` mints the
permanent receipt at `narrowhighway.org/s/<hash>`). See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## The Scribe (first tool)

A drafting loop: five writers compose a memo and its claims **by hand** (no tools), then

```
strip context → packets → CORE engine → SVD → feedback → next pass → reapply context → seal
```

The core is the **arithmetic datum**. The SVD over the claim matrix is a **spec-ambiguity
detector** — it shows where the writers read the spec two ways — not a truth signal. The verified
center draft is sealed through the core.

**The finding (recorded 2026-10-20):** five Claude writers agreed to 5–6 significant figures on
pass 1 (spread ≈ 0), yet the deterministic recompute still caught a wrong claim that consensus could
not see; zero broken after one feedback pass. Consensus is not truth; the verifier is.

## Run

```bash
pip install -e ".[dev]"                 # numpy + pytest
# the v2 app engine (ask/search/read/mesh/coach …) and the V3 verification engine
export NH_CORE_URL=https://api.narrowhighway.com
export NH_VERIFY_URL=http://127.0.0.1:8000     # github.com/matharrismma/Concordance-V3: `python -m concordance serve`
# (unset NH_VERIFY_URL and verification falls back to NH_CORE_URL)

# score a pass of drafts (writes report.json + feedback.md next to the drafts)
python -m nh_org.scribe.orchestrate pass 1 --root tests/fixtures

# seal the verified center draft — DRY RUN by default; add --seal to mint the receipt on the core
python -m nh_org.scribe.orchestrate final 2 --root tests/fixtures
```

## Test

```bash
python tools/record_core.py            # once: capture the core's verdicts (read-only) for offline replay
python -m pytest -q                     # boundary (no core import) + the Scribe loop against recorded verdicts
```

`NH_CORE_LIVE=1 pytest` also runs a live smoke test against the real core.
