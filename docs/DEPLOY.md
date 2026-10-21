# Deploy & cut over — the witness app onto narrowhighway.org

The witness app is a client of the core. It runs as its own service and serves `narrowhighway.org`
by composing the core's doors over HTTP. The core (concordance-2) keeps serving `.com` + the `api.`
door throughout; nothing here touches the engine.

**Status: LIVE as of 2026-10-21.** Steps 1–2 are done — `narrowhighway.org` is served by
`nh-org.service` on `:8010`, verified live, with the core's `:8001` kept as the rollback target.
Step 3 (removing dead core code) is not done; it stays gated. The commands below are the record of
how it was done and how to roll back or redo it.

**Principle: never leave the site unable to answer.** Deploy *alongside* first, prove it in
production, flip the domain with the old path one line away, and remove core code only afterward.
Every step has a rollback.

## Config

| env | default | meaning |
|---|---|---|
| `NH_CORE_URL` | `https://api.narrowhighway.com` | the core the app calls (on the box, `http://127.0.0.1:8002`) |
| `NH_ORG_HOST` / `NH_ORG_PORT` | `127.0.0.1` / `8010` | where the app listens |
| `NH_ORG_GATE` | `1` | the `.org` face opens the Gate (the Word woven in) |

## 1 — deploy alongside (non-breaking; nothing routed to it yet)

On the box (`nh@5.78.186.55`), beside `/home/nh/concordance-2`:

```sh
git clone https://github.com/matharrismma/witness /home/nh/witness
cd /home/nh/witness && python3 -m venv .venv && .venv/bin/pip install -e .
# run it as a user service (survives logout/restart):
#   ~/.config/systemd/user/nh-org.service  →  ExecStart=/home/nh/witness/.venv/bin/nh-serve
#   Environment=NH_CORE_URL=http://127.0.0.1:8002 NH_ORG_PORT=8010
systemctl --user daemon-reload && systemctl --user enable --now nh-org
```

Verify on the box (no public traffic yet):

```sh
curl -s http://127.0.0.1:8010/health            # {"ok":true,"surface":"witness",...}
curl -s "http://127.0.0.1:8010/book?q=what+does+scripture+say+about+honest+work" | head
```

## 2 — flip the domain (the one breaking step; instant rollback)

`deploy/Caddyfile` currently routes `narrowhighway.org` to the core's witness process on `:8001`.
Change that one block to the app, keep the old line commented for rollback:

```
narrowhighway.org {
    # was: reverse_proxy 127.0.0.1:8001   # core witness surface — rollback target
    reverse_proxy 127.0.0.1:8010          # the witness app
}
```

`caddy reload`. Watch the live site and the core logs. **Rollback:** restore the `:8001` line and
reload — the core still serves the full witness surface until step 3 removes it.

## 3 — per-piece cutover (remove core code; only after step 2 is proven)

The core KEEPS every door the app calls (`/ask`, `/verify`, `/mesh`, `/mesh/map`, `/groups`,
`/seal`, `/seals`, `/badges`, `/speak`, `/teachings`, `/decks`, `/coach/*`, `/playbook`) and the
whole engine. What is removed is the core's now-dead **witness site-serving** and the composition
modules the app replaced — one at a time, each proven unreferenced first:

```sh
# for each candidate (console.py site-serving, the witness HTML, mesh/groups/coach SURFACING, …):
grep -rn "import console" src/concordance | grep -v web/api   # nothing else uses it?
#   remove it, run the core's gate (benchmarks/assay/frontdoor/recall), deploy, watch .org.
```

Order mirrors the migration: Console → record surfacing → community surfacing → study/coach. A door
a verifier needs is NOT a candidate. Keep `docs/V3_BOUNDARY.md` in step with each removal.

**Do not run steps 2–3 unattended.** Flipping a live domain and deleting production-serving code is
the one destructive, irreversible-feeling part of V3; do it with eyes on the site and the rollback
ready, piece by piece.
