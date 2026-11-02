#!/usr/bin/env bash
# tools/ship.sh: ship the witness app. Fast-forward its checkout to origin/main, restart it, verify doors that
# reach both engines and the fallback, or roll back to the commit it started from.
#
#   ssh <box> 'bash -s' < tools/ship.sh
#
# The lead runs it from OUTSIDE the checkout it rewrites: bash reads a script as it runs, so a script inside the
# checkout would be rewritten under its own feet. Run as a file from inside WITNESS_DIR, it refuses.
#
# Settings (environment variables, with their defaults):
#   WITNESS_DIR   /home/nh/witness                  the checkout the app runs from
#   RESTART_CMD   sudo systemctl restart nh-org     how the app is restarted (run with bash -c)
#   APP           http://127.0.0.1:8010             where the app answers, for the checks
#   CURL          curl                              the HTTP client
#   PYTHON        python3                           reads the JSON answers
#   WAIT_TRIES    30                                how many times to ask /health after a restart
#   WAIT_SECONDS  2                                 the pause between those asks
#
# What it does:
#   0. takes the lock: one ship at a time. It makes the directory ship.lock in the checkout's git directory
#      (mkdir is atomic) and writes its pid and start time there; if the lock is already there it refuses, changing
#      nothing. It removes the lock only when it took it and ends on one of its own exits (0, 1, 2 or 3). A ship
#      killed outright, or by a signal, leaves the lock, and the next ship refuses: remove it by hand, and only after
#      confirming no ship is running and reading public /health;
#   1. records HEAD;
#   2. refuses, changing nothing, unless the checkout is on main with no tracked changes (untracked runtime files
#      are allowed) and HEAD has not diverged from origin/main. That is checked before the fetch, and again after
#      it; a refusal after the fetch has moved only the origin/main ref, never HEAD, the index or the files;
#   3. fetches, fast-forwards to origin/main, restarts, and waits for /health to answer 200;
#   4. checks, against APP: /health names the new HEAD; GET /s/045bc6ff... (a seal only the keeping's engine
#      holds, reached through the fallback) answers 200 and names the hash; GET /s/75cf60e5... (a V3 seal) answers
#      200; POST /verify?seal=0 with the claim 1234+4321=5555 answers 200, HOLDS, and is not sealed;
#      POST /console with "how many ounces in a pound" answers 200 and says 16 ounces;
#      GET /find_verifier?q=speed+of+light answers 200;
#   5. on any failure after the fast-forward, resets hard to the recorded commit, restarts, waits for /health and
#      exits nonzero.
#
# Its only POSTs are /verify?seal=0 (a read: V3 seals a POST /verify by default, ?seal=0 keeps it a read) and
# /console (which reaches the keeping's POST /ask: a conversation record each run, and a re-mint of the existing
# unit seal fbb2ce1b without a new ledger entry).
#
# A dropped session cannot stop it halfway: it ignores HUP and PIPE, and no message it fails to write stops it.
# It runs only once the whole script has arrived, and nothing it starts can read the script stream.
#
# Exit status: 0 shipped and verified; 2 refused, nothing changed; 1 a step or check failed after the
# fast-forward and the checkout was rolled back to the recorded commit, restarted, and answers /health at it;
# 3 the rollback itself failed, and the checkout or the app needs a human.
set -u -o pipefail
# A cut session must not stop a ship halfway. When the ssh link drops, the box's bash loses its reader and would
# die of SIGPIPE on its next message (or of SIGHUP): right after the fast-forward, say, with the new commit checked
# out and never restarted or rolled back. Ignore both, and let no message's failure stop the run.
trap '' HUP PIPE
SHIP_SELF="${BASH_SOURCE[0]:-}"   # this script's file, when it is run as one (empty when streamed by bash -s)

say() { printf 'ship: %s\n' "$*" >&2 2>/dev/null || true; }

LOCK=""            # the lock this run took, once it took it
LOCK_TOKEN=""      # what it wrote there, so it removes only its own
BODY_FILE=""
CONTROLLED=0       # set by finish: the run ended on one of its own exits

finish() { CONTROLLED=1; exit "$1"; }

on_exit() {        # the EXIT trap, set right after the lock is taken
    [ -n "$BODY_FILE" ] && rm -f "$BODY_FILE" 2>/dev/null
    if [ "$CONTROLLED" = 1 ] && [ -n "$LOCK" ]; then
        if [ ! -e "$LOCK/owner" ] || [ "$(cat "$LOCK/owner" 2>/dev/null)" = "$LOCK_TOKEN" ]; then
            rm -f "$LOCK/owner" 2>/dev/null
            rmdir "$LOCK" 2>/dev/null
        fi
    fi
    return 0
}

refuse() {
    say "REFUSED: $*"
    say "the checkout was not changed: HEAD, the index and the files are as they were"
    finish 2
}

http() {  # http METHOD PATH [JSON]: the answer's status in STATUS, its body in BODY_FILE
    : > "$BODY_FILE"
    if [ "$1" = POST ]; then
        STATUS=$("$CURL" -sS --max-time 60 -o "$BODY_FILE" -w '%{http_code}' -X POST \
                 -H 'content-type: application/json' --data-binary "$3" "$APP$2") || STATUS=000
    else
        STATUS=$("$CURL" -sS --max-time 60 -o "$BODY_FILE" -w '%{http_code}' "$APP$2") || STATUS=000
    fi
}

wait_health() {
    local i=0
    while [ "$i" -lt "$WAIT_TRIES" ]; do
        http GET /health
        [ "$STATUS" = 200 ] && return 0
        i=$((i + 1))
        sleep "$WAIT_SECONDS"
    done
    return 1
}

health_commit() {
    "$PYTHON" -c 'import json, sys; print(json.load(open(sys.argv[1], encoding="utf-8")).get("commit", ""))' \
        "$BODY_FILE" 2>/dev/null
}

holds_unsealed() {
    "$PYTHON" -c '
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
house = d.get("house") if isinstance(d.get("house"), dict) else {}
sys.exit(0 if d.get("verdict") == "HOLDS" and not d.get("seal") and not house.get("seal") else 1)
' "$BODY_FILE" 2>/dev/null
}

rollback() {
    say "FAILED: $*"
    say "rolling back to $OLD"
    if git reset --quiet --hard "$OLD" && [ "$(git rev-parse HEAD)" = "$OLD" ] \
            && bash -c "$RESTART_CMD" && wait_health && [ "$(health_commit)" = "$OLD" ]; then
        say "rolled back: the checkout is at $OLD, restarted, and /health names it"
        finish 1
    fi
    say "ROLLBACK FAILED: the checkout or the app needs a human (the recorded HEAD was $OLD)"
    finish 3
}

main() {
    WITNESS_DIR="${WITNESS_DIR:-/home/nh/witness}"
    RESTART_CMD="${RESTART_CMD:-sudo systemctl restart nh-org}"
    APP="${APP:-http://127.0.0.1:8010}"
    CURL="${CURL:-curl}"
    PYTHON="${PYTHON:-python3}"
    WAIT_TRIES="${WAIT_TRIES:-30}"
    WAIT_SECONDS="${WAIT_SECONDS:-2}"

    FALLBACK_SEAL=045bc6ffa8725277ddf45a65e256965641e6c9f0b7d761094e5286a85c359ad8
    V3_SEAL=75cf60e58c6f5a2189c9c76d6235e95eea99676e10379ef22f8bfa9de194ac98
    VERIFY_BODY='{"claim": "1234+4321=5555"}'
    CONSOLE_BODY='{"text": "how many ounces in a pound"}'

    # 0. Never from inside the checkout it rewrites.
    if [ -n "$SHIP_SELF" ] && [ -f "$SHIP_SELF" ]; then
        local self_dir wd
        self_dir=$(cd "$(dirname "$SHIP_SELF")" && pwd -P) || refuse "cannot tell where this script is"
        if wd=$(cd "$WITNESS_DIR" 2>/dev/null && pwd -P); then
            case "$self_dir/" in
                "$wd"/*) refuse "this script is inside $WITNESS_DIR, the checkout it rewrites;" \
                                "run it from outside: ssh <box> 'bash -s' < tools/ship.sh" ;;
            esac
        fi
    fi

    cd "$WITNESS_DIR" 2>/dev/null || refuse "there is no checkout at $WITNESS_DIR"
    [ "$(git rev-parse --is-inside-work-tree 2>/dev/null)" = true ] || refuse "$WITNESS_DIR is not a git checkout"

    # 0. One ship at a time: take the lock before anything else, and release it, through the EXIT trap, only on
    #    this run's own exits. Never reclaim a lock left behind: a ship killed mid-run leaves one, and the next
    #    ship must refuse until a human has looked.
    local git_dir held
    git_dir=$(cd "$(git rev-parse --git-dir)" 2>/dev/null && pwd -P) || refuse "cannot find the git directory"
    if ! mkdir "$git_dir/ship.lock" 2>/dev/null; then
        held=$(cat "$git_dir/ship.lock/owner" 2>/dev/null || echo "no owner recorded")
        refuse "another ship holds the lock $git_dir/ship.lock ($held). One ship at a time. Remove it by hand" \
               "(rm -r $git_dir/ship.lock) only after confirming no ship is running and reading public /health"
    fi
    LOCK="$git_dir/ship.lock"
    trap on_exit EXIT
    LOCK_TOKEN="pid $$, started $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf '%s\n' "$LOCK_TOKEN" > "$LOCK/owner" 2>/dev/null || refuse "cannot write the lock's owner"
    say "took the lock $LOCK ($LOCK_TOKEN)"

    # 1. Record HEAD.
    OLD=$(git rev-parse --verify -q HEAD) || refuse "HEAD does not resolve to a commit"
    say "recorded HEAD $OLD"

    # 2. Refuse, changing nothing.
    [ "$(git symbolic-ref -q HEAD)" = refs/heads/main ] || refuse "the checkout is not on main"
    local dirty
    dirty=$(GIT_OPTIONAL_LOCKS=0 git status --porcelain --untracked-files=no) || refuse "git status failed"
    [ -z "$dirty" ] || refuse "the checkout has tracked changes: $(printf '%s' "$dirty" | head -n 5 | tr '\n' ' ')"
    git rev-parse --verify -q origin/main >/dev/null || refuse "there is no origin/main"
    git merge-base --is-ancestor HEAD origin/main || refuse "HEAD $OLD has diverged from origin/main"

    BODY_FILE=$(mktemp) || refuse "mktemp failed"
    STATUS=000

    # 3. Fetch, fast-forward, restart, wait.
    git fetch --quiet origin main || refuse "git fetch failed"
    git merge-base --is-ancestor HEAD origin/main || refuse "HEAD $OLD has diverged from origin/main as fetched"
    git merge --ff-only --quiet origin/main || rollback "the fast-forward failed"
    NEW=$(git rev-parse --verify HEAD) || rollback "HEAD does not resolve after the fast-forward"
    say "fast-forwarded $OLD -> $NEW"
    bash -c "$RESTART_CMD" || rollback "the restart failed"
    wait_health || rollback "/health did not answer 200 after the restart"

    # 4. Verify the doors, against APP.
    [ "$(health_commit)" = "$NEW" ] || rollback "/health names $(health_commit), not $NEW"
    http GET "/s/$FALLBACK_SEAL"
    [ "$STATUS" = 200 ] && grep -qF "$FALLBACK_SEAL" "$BODY_FILE" \
        || rollback "GET /s/$FALLBACK_SEAL answered $STATUS without naming the hash (the fallback)"
    http GET "/s/$V3_SEAL"
    [ "$STATUS" = 200 ] || rollback "GET /s/$V3_SEAL answered $STATUS (V3)"
    http POST "/verify?seal=0" "$VERIFY_BODY"
    [ "$STATUS" = 200 ] && holds_unsealed || rollback "POST /verify?seal=0 answered $STATUS, not HOLDS unsealed"
    http POST /console "$CONSOLE_BODY"
    [ "$STATUS" = 200 ] && grep -qF '16 ounces' "$BODY_FILE" \
        || rollback "POST /console answered $STATUS without 16 ounces"
    http GET "/find_verifier?q=speed+of+light"
    [ "$STATUS" = 200 ] || rollback "GET /find_verifier answered $STATUS"

    say "shipped $OLD -> $NEW: /health, the fallback, V3, /verify, /console and /find_verifier all answer"
    finish 0
}

# The whole script is one function, run only from this last line, with stdin from /dev/null: streamed through
# bash -s, a stream cut short defines no main and runs nothing, and no child (git, curl, the restart) can read
# the rest of the script as its input.
main "$@" </dev/null
