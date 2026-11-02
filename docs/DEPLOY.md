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
| `NH_CORE_URL` | `https://api.narrowhighway.com` | the core the app calls (on the box, `http://127.0.0.1:8001`, the engine's witness face) |
| `NH_ORG_HOST` / `NH_ORG_PORT` | `127.0.0.1` / `8010` | where the app listens |
| `NH_ORG_GATE` | `1` | the `.org` face opens the Gate (the Word woven in) |

## Ship: every release after the cutover

A release is a commit on `origin/main`. The lead ships it with [`tools/ship.sh`](../tools/ship.sh), run on the
box from **outside** the checkout it rewrites (bash reads a script as it runs, so a script inside the checkout
would be rewritten under its own feet; run as a file from inside the checkout, it refuses):

```sh
ssh <box> 'bash -s' < tools/ship.sh
```

| env | default | meaning |
|---|---|---|
| `WITNESS_DIR` | as set in `tools/ship.sh` | the checkout the app runs from |
| `RESTART_CMD` | `sudo systemctl restart nh-org` | how the app is restarted |
| `APP` | `http://127.0.0.1:8010` | where the app answers, for the checks |
| `CURL` / `PYTHON` | `curl` / `python3` | the HTTP client, and what reads the JSON answers |
| `WAIT_TRIES` / `WAIT_SECONDS` | `30` / `2` | how long to wait for `/health` after a restart |

What it does, in order:

0. Takes the lock: one ship at a time. It makes the directory `ship.lock` in the checkout's git directory
   (`mkdir` is atomic) and writes its pid and start time there. If the lock is already there, it refuses
   (exit 2) and changes nothing.
1. Records HEAD.
2. Refuses (exit 2) unless the checkout is on `main`, has no tracked changes (untracked runtime files are
   allowed) and has not diverged from `origin/main`, checked before the fetch and again after it. A refusal
   leaves HEAD, the index and the files as they were.
3. Fetches, fast-forwards to `origin/main`, restarts and waits for `/health` to answer 200.
4. Checks, against `APP`, doors that reach both engines and the fallback:
   - `/health` names the new HEAD;
   - `GET /s/045bc6ff…` (held only by the keeping's engine, reached through the fallback) answers 200 and names
     the hash;
   - `GET /s/75cf60e5…` (a V3 seal) answers 200;
   - `POST /verify?seal=0` with the claim `1234+4321=5555` answers 200, HOLDS, and is not sealed;
   - `POST /console` with "how many ounces in a pound" answers 200 and says 16 ounces;
   - `GET /find_verifier?q=speed+of+light` answers 200.
5. On any failure after the fast-forward, resets hard to the recorded commit, restarts, waits for `/health` to
   name that commit, and exits 1. Exit 3 means the rollback itself failed and a human is needed.

A dropped session cannot stop it halfway: it ignores HUP and PIPE, and no message it fails to write stops it.
The whole script is one function run from its last line with stdin from `/dev/null`, so a stream cut short
runs nothing, and nothing it starts (git, curl, the restart) can read the script as its input.

**One ship at a time.** A ship removes its lock when it ends on one of its own exits (0, 1, 2 or 3), and only
the lock it took. It never reclaims a lock left behind. So after a dropped session, the ship finishes on its own,
unattended. Before running it again:

1. Read public `/health` (`https://narrowhighway.org/health`), which names the commit the app runs.
2. Check on the box for the lock, `ship.lock` in the checkout's git directory (`.git/ship.lock`).

While the lock is there, a ship is running or one was killed: a second ship refuses. If no ship is running,
the lock is a killed ship's. Confirm that, read public `/health` and the checkout's HEAD, then remove the lock by
hand (`rm -r` it) and run again.

Exit 0 means shipped and verified. Its only POSTs are `/verify?seal=0` (a read: V3 seals a `POST /verify` by
default, and `?seal=0` keeps it a read) and `/console`, which reaches the keeping's `POST /ask`: that writes a
conversation record each run and re-mints the existing unit seal `fbb2ce1b…` without a new ledger entry.
`tests/test_ship.py` runs it against a throwaway origin and clone and proves each branch. Never run it from
inside the checkout, and never edit files on the box: a tracked change there makes the next ship refuse.

## 1 — deploy alongside (non-breaking; nothing routed to it yet)

On the box (the lead's ssh target; this repo names no host, address or account), beside the concordance-2
checkout, clone into the directory `WITNESS_DIR` names in `tools/ship.sh`:

```sh
git clone https://github.com/matharrismma/witness "$WITNESS_DIR"
```

`nh-org` is a **system** service (not a user one). Its unit sets `WorkingDirectory` and
`Environment=PYTHONPATH` to that checkout and runs `ExecStart=/usr/bin/python3 -m nh_org.serve`, so the app
imports straight from the checkout and `/health` names that checkout's commit. The unit's `Environment` also
carries the app's settings, all on the box's own loopback:

| key | value | why |
|---|---|---|
| `NH_CORE_URL` | `http://127.0.0.1:8001` | the keeping's engine (concordance-2) on its witness face, which `.org` must use (`:8002` is its secular face), for everything but verification |
| `NH_VERIFY_URL` | `http://127.0.0.1:8020` | V3, the verification doors and seals (set in a drop-in for the unit; Concordance-V3 `deploy/README.md`); unset, verification falls back to `NH_CORE_URL` and the V3 boundary is lost |
| `NH_ORG_HOST` / `NH_ORG_PORT` | `127.0.0.1` / `8010` | where the app listens (Caddy proxies `narrowhighway.org` here) |
| `NH_ORG_GATE` | `1` | the `.org` face opens the Gate |

Restart it with:

```sh
sudo systemctl restart nh-org
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
