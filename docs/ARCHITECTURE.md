# V3 architecture — the split

**Decision (2026-10-20).** Narrow Highway splits into a pure **core engine** and an **application
layer**. This repo is the application layer, served at `narrowhighway.org`. The core stays in the
`concordance-2` repo, served at `narrowhighway.com` plus the `api.`/MCP door.

```
                      narrowhighway.org  (this repo — the ancillary layer)
                      ┌───────────────────────────────────────────────┐
                      │  witness · record · community · coach · Console │
                      │  Scribe (first tool)                            │
                      │                                                 │
                      │  nh_org/core_client.py  ── the ONLY core link ──┼──┐
                      └───────────────────────────────────────────────┘  │ HTTP
                                                                          │ POST /verify
                      narrowhighway.com / api.  (concordance-2 — the core)│ ?seal=0 read · ?seal=1 mint
                      ┌───────────────────────────────────────────────┐  │
                      │  verify · discern · audit · 94 verifiers        │◄─┘
                      │  corpus · cas · ledger · seals · the map · MCP  │
                      └───────────────────────────────────────────────┘
                               one engine · one corpus · two surfaces
```

## The rule

**One engine, one corpus, never isolated.** The `.org` app holds no verifier and no corpus of its
own. Every check and every seal crosses the HTTP boundary to the one core engine. The core is the
single source of verification truth for both faces; the `.org` app adds surfaces, orchestration and
the witness record on top.

`tests/test_boundary.py` pins this: importing the whole app loads no `concordance` module, and
`core_client` speaks exactly one core path (`/verify`). A new core coupling must go through that
client (or a reviewed addition to it), never a direct import.

## What is core vs what moved here

| Core (concordance-2, serves .com + api/MCP) | Ancillary (this repo, serves .org) |
|---|---|
| verify, discern, audit, derivation, the 94 verifiers | the Scribe, and (to follow) the Console, coach, decks, playbook |
| corpus, cas, ledger, seals, the map (chains/graph/roots), sticks | the witness record: seals surfaced, badges, professions, consent, moderation |
| domain_resolver, candidates, warrant, factfind | community: mesh, groups, formation, flock, push, lighthouse node |
| MCP core + library profiles; the gate/kernel | witness surfacing of scripture/teachings/parable (the verifiers stay core) |

The witness **verifiers** (scripture, theology) remain in the core engine — they are deterministic
verification, part of the one engine. What moves to `.org` is their **surfacing** and the record
they produce.

## The contract this app depends on

`POST {NH_CORE_URL}/verify`

- `{"steps": [ {"id","domain","spec"} ... ]}` → `{verdict, trail:[{id,domain,status,detail}], house:{seal}}`
- `{"claim": "<plain sentence>"}` → `{verdict, checks:[...], receipt, coverage}`
- `?seal=0` (default here) is read-only; `?seal=1` mints the receipt at `narrowhighway.org/s/<hash>`.

`NH_CORE_URL` defaults to `https://api.narrowhighway.com`; point it at a local core to develop offline.

## Status (2026-10-20)

Boundary carved, app scaffolded. Landed and proven against the core:

- **Scribe** — a loop over `/verify` (+ seal); consensus is not truth, the verifier is.
- **Console** — a composition over `/ask` (`nh_org/console`). The Console was evaluated for the core
  and did not fit: its spine is engine-shaped but it was welded to the ancillary voice/witness/coach/
  scribe layer, so it moves here and composes the core doors instead. With the Gate open (the
  `.org`/witness face), it now surfaces the Word (`path.anchor`, verbatim + cited), the shepherd step
  and the public-domain witness **cloud** — all composed from `/ask`, never generated. The cloned
  **voice** (audio via `/speak`) is a declared seam, gated on ElevenLabs credits; the book render and
  keep are app-side UI still to come — see [MIGRATION.md](MIGRATION.md).

The `core_client` door allowlist (`CORE_DOORS`) is pinned by `tests/test_boundary.py`. Next: the
Console book render, then the witness record and community, then the `.org` deployment. The order
is in [MIGRATION.md](MIGRATION.md).

The Console now also **speaks** (`console.speak()` over the core `/speak` ceiling — audio with
ElevenLabs credits, the honest 503 floor without) and **keeps** every exchange in the **Palace**
(`nh_org/palace.py`): a memory palace of `(room, position)` loci on a tensor, recalled by a sort.
See [PALACE.md](PALACE.md).
