# Migration — everything ancillary moves here

V3 (2026-10-20): the core engine (`concordance-2`, serving `narrowhighway.com` + the `api.`/MCP
door) keeps only verification, the keeping, the map and the doors. Everything else — the composed
experiences, the witness record, the community — moves into this app and reaches the engine over
HTTP through `nh_org.core_client` (the reviewed door allowlist `CORE_DOORS`). The app reimplements
no verifier and holds no corpus.

**The Console was evaluated for the core and did not fit.** Its spine (ask → find/verify/cite →
answer + trail + one next step) is engine-shaped and is composed from the core's `/ask` door. But
the Console as it stood was welded to the ancillary layer — the cloned voice (RADIO), the
public-domain witness cloud, the coach/shepherd weave, the book render, keep/scribe. Keeping it in
the core would drag all of that into the engine, so it moves here too; the engine keeps the
primitive doors it composes.

## Order (low coupling / high value first)

| # | Piece | Lands as | Status |
|---|---|---|---|
| 1 | **Scribe** | a loop over `/verify` (+ seal) | **done** |
| 2 | **Console spine** | a composition over `/ask` | **done** |
| 3 | Console enrichments | voice (RADIO), witness cloud, coach weave, book render, keep — wired app-side; each found/verified, never generated | next |
| 4 | Witness **record** | professions, self-attest, witnesses, badges — compose the core's seal/record doors | planned |
| 5 | **Community** | mesh, groups, formation, flock, push, lighthouse node | planned |
| 6 | Study / coach | coach, trajectory, decks, playbook, teachings & parable surfaces | planned |

## How each piece moves (the safe cut-over)

1. Build it here as a composition over the core doors it needs (adding a door to `CORE_DOORS` only
   when the engine genuinely must expose a new primitive — a reviewed change, pinned by
   `tests/test_boundary.py`).
2. Prove it against the core (recorded fixtures offline + a live smoke).
3. Repoint `narrowhighway.org` at this app for that surface.
4. Only then remove the module from the core. The core serves both faces until the app is ready; the
   engine is never left unable to answer.

## What stays in the core, always

Verification (`verify`, `discern`, `audit`, the verifiers), the keeping and the map (`corpus`, `cas`,
`ledger`, seals, chains/graph/roots, sticks), and the doors (`/verify`, `/ask`, `/search`, `/read`,
`/resolve`, `/word_study`, MCP). The witness **verifiers** (scripture, theology) stay — deterministic
checking is core; only their surfacing is here. One engine, one corpus, two surfaces.
