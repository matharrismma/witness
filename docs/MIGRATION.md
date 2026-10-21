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
| 3 | Console enrichments | the Word (`path.anchor`), the shepherd step (`path`) and the witness **cloud** — composed from `/ask` with the Gate open; found/verified, never generated | **done** (voice below) |
| 3v | Console **voice** (RADIO) | `console.speak()` over the core `/speak` ceiling; audio/mpeg with credits, the 503 floor without — never fabricated | **wired** (floor until credits) |
| 3b | Console **keep** | the **Palace** (`nh_org/palace.py`): a memory palace — exchanges at `(room, position)` loci on a tensor, recall by a sort; `dispatch(keep=True, palace=…)` files each exchange | **done** |
| 3r | Console **book render** | `nh_org/console/book.py` — a still, standalone E-Ink page of the answer (the Word, a static trail, the cloud, one next step); escaped, themed, no script | **done** |
| 4 | Witness **record** (read) | `nh_org/record.py` — fetch a sealed receipt (`/seal`), the ledger tally (`/seals`), compose an unsigned evidence badge (`/badges`) | **done** |
| 4w | Record **signed writes** | professions (`/mesh/node`), self-attest, bind-a-badge (`/attest`) — the holder's OWN signed request; the app never holds a key or signs | **seam** — docs/RECORD.md; identity model required |
| 5 | **Community** (read) | `nh_org/community.py` — the mesh overview (`/mesh`), the map around a node / the gated invite (`/mesh/map`), the study groups (`/groups`) | **done** |
| 5w | Community **writes** | join (`/mesh/node`), post (`/mesh/post`), a door blessing (`/mesh/door`), link/tend/invite/redeem, group join/contribute — the member's own authorized (mostly signed) act | **seam** — docs/COMMUNITY.md |
| 6 | **Study / coach** (read) | `nh_org/study.py` — the Words in Red (`/teachings`), the decks (`/decks`), the coach overview/next (`/coach/overview`, `/coach/next`), the playbook (`/playbook`) | **done** |
| 6w | Study **writes** | mastery, create/export/import a study, save a trajectory, submit a playbook entry — the learner's own record | **seam** — docs/STUDY.md |
| 7 | **Web server** | `nh_org/serve.py` — serves `.org`: the landing ask box, `/book?q=` (a still page), `/console` (JSON), `/health`, and the read surfaces | **done** |
| 8 | **Deploy + flip** | `nh-org.service` on the box (:8010); `narrowhighway.org` flipped to it, verified live; core kept as rollback | **LIVE** (2026-10-21) |
| 8c | Per-piece **core cleanup** | remove the core's now-dead witness serving + replaced modules, one at a time | **gated** — docs/DEPLOY.md §3, do with eyes on the site |

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
