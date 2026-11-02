"""tools/ship.sh, run with bash against a throwaway bare origin and clone, with a stand-in restart and HTTP client.

Never the box, never the network: the restart is a bash line that records the commit it "restarted" at, and the
HTTP client is a stand-in that answers from a table and logs every request. Git runs isolated from this machine's
configuration and from any inherited GIT_* variable.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SHIP = ROOT / "tools" / "ship.sh"
FALLBACK = "045bc6ffa8725277ddf45a65e256965641e6c9f0b7d761094e5286a85c359ad8"   # the keeping's, via the fallback
V3 = "75cf60e58c6f5a2189c9c76d6235e95eea99676e10379ef22f8bfa9de194ac98"
APP = "http://app.test"
VERIFY = ["POST", APP + "/verify?seal=0", {"claim": "1234+4321=5555"}]
CONSOLE = ["POST", APP + "/console", {"text": "how many ounces in a pound"}]
DOORS = [["GET", APP + "/health", None], ["GET", APP + "/s/" + FALLBACK, None], ["GET", APP + "/s/" + V3, None],
         VERIFY, CONSOLE, ["GET", APP + "/find_verifier?q=speed+of+light", None]]
# the app as it answers when every door is well; "{commit}" is the commit it was last restarted at
WELL = {"GET " + APP + "/health": [200, '{"ok": true, "surface": "witness", "commit": "{commit}"}'],
        "GET " + APP + "/s/" + FALLBACK: [200, "<p>The receipt " + FALLBACK + "</p>"],
        "GET " + APP + "/s/" + V3: [200, '{"content_hash": "' + V3 + '"}'],
        "POST " + APP + "/verify?seal=0": [200, '{"verdict": "HOLDS", "seal": null}'],
        "POST " + APP + "/console": [200, '{"answer": "1 pound = 16 ounces"}'],
        "GET " + APP + "/find_verifier?q=speed+of+light": [200, '{"verifiers": []}']}

# The stand-in HTTP client: parses the curl arguments ship.sh uses, logs [method, url, body], writes the body to -o
# and prints the status for -w. An answer may depend on the commit the app was last restarted at; "down" is no
# answer at all (curl prints 000 and fails).
FAKE_CURL = r'''
import json, os, sys
args, out, fmt, method, data, url, i = sys.argv[1:], None, None, "GET", None, None, 0
while i < len(args):
    a = args[i]
    if a in ("-o", "-w", "-X", "-H", "--data-binary", "--max-time"):
        out, fmt, method, data = ({"-o": args[i + 1]}.get(a, out), {"-w": args[i + 1]}.get(a, fmt),
                                  {"-X": args[i + 1]}.get(a, method), {"--data-binary": args[i + 1]}.get(a, data))
        i += 2
    elif a.startswith("-"):
        i += 1
    else:
        url, i = a, i + 1
with open(os.environ["FAKE_LOG"], "a", encoding="utf-8") as f:
    f.write(json.dumps([method, url, None if data is None else json.loads(data)]) + "\n")
state = os.environ["FAKE_STATE"]
commit = open(state, encoding="utf-8").read().strip() if os.path.exists(state) else ""
answer = json.load(open(os.environ["FAKE_TABLE"], encoding="utf-8")).get(method + " " + url)
if isinstance(answer, dict):
    answer = answer.get(commit, answer.get("*"))
if answer == "down":
    sys.stdout.write("000")
    sys.exit(7)
status, body = answer or (404, '{"error": "not found"}')
open(out, "w", encoding="utf-8").write(body.replace("{commit}", commit))
sys.stdout.write(str(status) if fmt == "%{http_code}" else "")
'''
# The stand-in restart: records the commit it restarted at (the app then reports it), and fails on the call
# FAKE_RESTART_FAILS names (1 = the first restart, 2 = the second, ...).
RESTART = ('git rev-parse HEAD >> "$FAKE_RESTARTS" && git rev-parse HEAD > "$FAKE_STATE" && '
           '[ "$(( $(wc -l < "$FAKE_RESTARTS") ))" != "${FAKE_RESTART_FAILS:-0}" ]')
# A restart during which a second ship is started on the same checkout (once: the first restart only), as a lead
# re-running the ship after a dropped session would; its exit code and messages are kept beside the run.
OVERLAP = ('if [ ! -e "$FAKE_SECOND.started" ]; then : > "$FAKE_SECOND.started"; '
           'bash -s < "$FAKE_SHIP" > /dev/null 2> "$FAKE_SECOND.err"; echo "$?" > "$FAKE_SECOND.code"; fi; ' + RESTART)


def _locked(box):
    return (box / ".git" / "ship.lock").exists()


def _bash():
    """bash, where it is: on PATH (not Windows' WSL launcher), or beside git as Git for Windows ships it."""
    b = shutil.which("bash")
    if b and not (os.name == "nt" and "system32" in b.lower()):
        return b
    g = shutil.which("git")
    for parent in (Path(g).resolve().parents if g else ()):
        for c in (parent / "bin" / "bash.exe", parent / "usr" / "bin" / "bash.exe"):
            if c.is_file():
                return str(c)
    return None


def _fwd(p):
    return str(p).replace("\\", "/")


def _git_env(tmp):
    """This process's environment without any inherited GIT_* variable, and git isolated from this machine."""
    cfg = tmp / "gitconfig"
    cfg.write_text("", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL=str(cfg), GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME="t",
               GIT_AUTHOR_EMAIL="t@example.invalid", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")
    return env


class _World:
    """A bare origin whose main went A -> B -> C -> NEW (three commits past A, as the first real ship crosses many),
    and clones of it standing where the box stands before a ship: on main at A, with origin/main known only as A.
    A rollback must land on A, the recorded commit, not on NEW's parent."""

    def __init__(self, tmp):
        self.tmp, self.env, self.n = tmp, _git_env(tmp), 0
        self.origin = tmp / "origin.git"
        self.seed = tmp / "seed"
        self.seed.mkdir()
        self.git("init", "-q", cwd=self.seed)
        self.git("symbolic-ref", "HEAD", "refs/heads/main", cwd=self.seed)
        self.A = self.commit("A")
        self.git("init", "-q", "--bare", str(self.origin), cwd=tmp)
        self.git("symbolic-ref", "HEAD", "refs/heads/main", cwd=self.origin)
        self.git("push", "-q", str(self.origin), "main", cwd=self.seed)
        self.B, self.C, self.NEW = (self.commit(t) for t in ("B", "C", "NEW"))
        self.git("push", "-q", str(self.origin), "main", cwd=self.seed)

    def git(self, *args, cwd):
        return subprocess.run(["git", *args], cwd=cwd, env=self.env, check=True, capture_output=True,
                              text=True).stdout.strip()

    def commit(self, text, cwd=None):
        cwd = cwd or self.seed
        (cwd / "app.txt").write_text(text + "\n", encoding="utf-8")
        self.git("add", "app.txt", cwd=cwd)
        self.git("commit", "-q", "-m", text, cwd=cwd)
        return self.git("rev-parse", "HEAD", cwd=cwd)

    def clone(self):
        self.n += 1
        c = self.tmp / f"box{self.n}"
        self.git("clone", "-q", "-b", "main", str(self.origin), str(c), cwd=self.tmp)
        self.git("reset", "-q", "--hard", self.A, cwd=c)
        self.git("update-ref", "refs/remotes/origin/main", self.A, cwd=c)
        return c

    def head(self, c):
        return self.git("rev-parse", "HEAD", cwd=c)

    def second(self):
        """The second ship OVERLAP started during the last run's restart: (its exit code, its messages)."""
        run = self.last_run
        return int((run / "second.code").read_text().strip()), (run / "second.err").read_text(encoding="utf-8")

    def tracking(self, c):
        return self.git("rev-parse", "refs/remotes/origin/main", cwd=c)

    def ship(self, clone, table=None, *, stdin=True, script=SHIP, data=None, close_stderr=False, hold_stdin=False,
             **extra):
        """Run the ship against `clone`: as the lead runs it (bash -s, the script on stdin; `data` replaces the
        script's bytes, to cut the stream short), or as a file. `close_stderr` closes the reader of its stderr
        before it starts, as a dropped ssh session does. `hold_stdin` (file mode) gives it a stdin that stays open
        and never sends anything, as an ssh channel does. `extra` overrides any setting (RESTART_CMD, ...)."""
        bash = _bash()
        run = self.tmp / f"run{self.n}-{len(list(self.tmp.glob('run*')))}"
        run.mkdir()
        (run / "table.json").write_text(json.dumps(WELL if table is None else table), encoding="utf-8")
        (run / "fake_curl.py").write_text(FAKE_CURL, encoding="utf-8")
        curl = run / "curl"
        curl.write_bytes(b'#!/usr/bin/env bash\nexec "$FAKE_PYTHON" "$FAKE_CURL" "$@"\n')
        curl.chmod(0o755)
        env = dict(self.env, WITNESS_DIR=_fwd(clone), APP=APP, CURL=_fwd(curl), PYTHON=_fwd(sys.executable),
                   RESTART_CMD=RESTART, WAIT_TRIES="2", WAIT_SECONDS="0", FAKE_PYTHON=_fwd(sys.executable),
                   FAKE_CURL=_fwd(run / "fake_curl.py"), FAKE_TABLE=_fwd(run / "table.json"),
                   FAKE_LOG=_fwd(run / "log"), FAKE_STATE=_fwd(run / "state"), FAKE_RESTARTS=_fwd(run / "restarts"),
                   FAKE_SHIP=_fwd(SHIP), FAKE_SECOND=_fwd(run / "second"))
        env.update(extra)
        self.last_run = run
        if close_stderr:
            p = subprocess.Popen([bash, "-s"], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.PIPE, env=env, cwd=self.tmp)
            p.stderr.close()                                     # no one will read what it says from here on
            p.stdin.write(script.read_bytes() if data is None else data)
            p.stdin.close()
            r = subprocess.CompletedProcess(p.args, p.wait(timeout=300), b"", b"")
        elif stdin:
            r = subprocess.run([bash, "-s"], input=script.read_bytes() if data is None else data, env=env,
                               capture_output=True, cwd=self.tmp)
        elif hold_stdin:
            with open(run / "stderr", "wb") as err_file:
                p = subprocess.Popen([bash, _fwd(script)], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                     stderr=err_file, env=env, cwd=self.tmp)
                try:
                    code = p.wait(timeout=90)                      # a child that reads stdin would wait forever
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait()
                    code = "hung: a child read the open stdin"
                finally:
                    p.stdin.close()
            r = subprocess.CompletedProcess(p.args, code, b"", (run / "stderr").read_bytes())
        else:
            r = subprocess.run([bash, _fwd(script)], env=env, capture_output=True, cwd=self.tmp)
        log = run / "log"
        calls = [json.loads(ln) for ln in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []
        restarts = (run / "restarts").read_text().split() if (run / "restarts").exists() else []
        return r.returncode, r.stderr.decode("utf-8", "replace"), calls, restarts


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    if not _bash():
        pytest.skip("bash is not installed")
    if not shutil.which("git"):
        pytest.skip("git is not installed")
    return _World(tmp_path_factory.mktemp("ship"))


def _only_reads(calls):
    """The ship's only POSTs are /verify?seal=0 and /console, and every /verify carries seal=0."""
    assert [c for c in calls if c[0] != "GET"] in ([VERIFY, CONSOLE], [VERIFY], [])
    assert all("seal=0" in c[1] for c in calls if "/verify" in c[1])


def test_ship_fast_forwards_restarts_and_verifies_both_engines_and_the_fallback(world):
    """Run as the lead runs it (bash -s, from outside the checkout): it fast-forwards the checkout from A over
    three commits to origin/main's NEW, restarts once, waits for /health, checks every door in order and exits 0.
    An untracked runtime file in the checkout is allowed and kept. The defaults are the box's. A session cut
    under it cannot stop it halfway: with no reader left on its stderr, with a SIGHUP mid-run, or with a restart
    command that reads stdin, it still restarts, checks every door and exits 0; and a stream cut short runs
    nothing at all. One ship at a time: it takes the lock before it records HEAD and removes it when it ends, and a
    second ship started during its restart refuses with exit 2, changing nothing, while the first ships."""
    box = world.clone()
    (box / "runtime.log").write_text("the app's own file\n", encoding="utf-8")
    code, err, calls, restarts = world.ship(box)
    assert code == 0, err
    assert world.head(box) == world.tracking(box) == world.NEW and (box / "app.txt").read_text() == "NEW\n"
    assert restarts == [world.NEW]
    assert calls == DOORS                                       # /health once (it answered), then each door once
    _only_reads(calls)
    assert (box / "runtime.log").read_text() == "the app's own file\n"
    assert f"recorded HEAD {world.A}" in err and f"shipped {world.A} -> {world.NEW}" in err
    assert err.index("took the lock") < err.index("recorded HEAD") and not _locked(box)

    box = world.clone()
    code, err, calls, restarts = world.ship(box, RESTART_CMD=OVERLAP)
    second, second_err = world.second()
    assert second == 2 and "another ship holds the lock" in second_err and "ship.lock" in second_err, second_err
    assert "by hand" in second_err and "public /health" in second_err and "recorded HEAD" not in second_err
    assert code == 0, err
    assert world.head(box) == world.NEW and restarts == [world.NEW] and calls == DOORS    # the second did nothing
    assert not _locked(box)
    text = SHIP.read_text(encoding="utf-8")
    for default in ('WITNESS_DIR="${WITNESS_DIR:-/home/nh/witness}"',
                    'RESTART_CMD="${RESTART_CMD:-sudo systemctl restart nh-org}"',
                    'APP="${APP:-http://127.0.0.1:8010}"'):
        assert default in text, default

    cut = {"no one reads its stderr": dict(close_stderr=True),
           "a SIGHUP while it restarts": dict(RESTART_CMD='kill -HUP "$PPID"; ' + RESTART),
           "a restart that reads stdin": dict(RESTART_CMD="cat >/dev/null; " + RESTART)}
    for why, how in cut.items():
        box = world.clone()
        code, _err, calls, restarts = world.ship(box, **how)
        assert code == 0, why
        assert world.head(box) == world.NEW and restarts == [world.NEW] and calls == DOORS, why
        assert not _locked(box), why

    whole = SHIP.read_bytes()
    last = whole.rstrip(b"\n").rfind(b"\n") + 1                  # the start of the last line, which runs main
    assert whole[last:].startswith(b"main ")
    for end in (len(whole) // 4, len(whole) // 2, whole.index(b"    # 3. Fetch"), whole.index(b'    say "shipped'),
                last):
        box = world.clone()
        _code, _err, calls, restarts = world.ship(box, data=whole[:end])
        assert world.head(box) == world.tracking(box) == world.A and (box / "app.txt").read_text() == "A\n", end
        assert calls == [] and restarts == [] and not _locked(box), end


def test_ship_refuses_a_dirty_checkout_changing_nothing(world):
    """A tracked change, staged or not, is refused with exit 2 before anything: no fetch (origin/main still A),
    no fast-forward, no restart, no request, and the change itself left exactly as it was. The lock it took is
    gone again."""
    for stage in (False, True):
        box = world.clone()
        (box / "app.txt").write_text("edited on the box\n", encoding="utf-8")
        if stage:
            world.git("add", "app.txt", cwd=box)
        code, err, calls, restarts = world.ship(box)
        assert code == 2 and "tracked changes" in err, err
        assert world.head(box) == world.tracking(box) == world.A
        assert (box / "app.txt").read_text() == "edited on the box\n"
        assert world.git("diff", "--cached", "--name-only", cwd=box) == ("app.txt" if stage else "")
        assert calls == [] and restarts == []
        assert "took the lock" in err and not _locked(box)          # a refusal after the lock releases it


def test_ship_refuses_a_diverged_checkout_changing_nothing(world):
    """A commit made on the box, a checkout not on main, or an origin/main that no longer contains HEAD once
    fetched, is refused with exit 2: HEAD and the files stay where they were, nothing restarts, nothing is asked."""
    box = world.clone()
    local = world.commit("made on the box", cwd=box)
    code, err, calls, restarts = world.ship(box)
    assert code == 2 and "diverged" in err, err
    assert world.head(box) == local and world.tracking(box) == world.A        # refused before the fetch
    assert calls == [] and restarts == [] and not _locked(box)

    box = world.clone()
    world.git("checkout", "-q", "-b", "other", cwd=box)
    code, err, calls, restarts = world.ship(box)
    assert code == 2 and "not on main" in err, err
    assert world.head(box) == world.A and calls == [] and restarts == [] and not _locked(box)

    box = world.clone()                                          # origin's main rewritten: it no longer holds A
    rewritten = world.tmp / "rewritten"
    world.git("clone", "-q", "-b", "main", str(world.origin), str(rewritten), cwd=world.tmp)
    world.git("checkout", "-q", "--orphan", "fresh", cwd=rewritten)
    orphan = world.commit("an unrelated history", cwd=rewritten)
    world.git("push", "-q", "--force", str(world.origin), "fresh:main", cwd=rewritten)
    try:
        code, err, calls, restarts = world.ship(box)
        assert code == 2 and "diverged from origin/main as fetched" in err, err
        assert world.head(box) == world.A and (box / "app.txt").read_text() == "A\n"
        assert world.tracking(box) == orphan                     # only the fetch's own ref moved
        assert calls == [] and restarts == [] and not _locked(box)
    finally:
        world.git("push", "-q", "--force", str(world.origin), f"{world.NEW}:refs/heads/main", cwd=world.seed)


def test_a_failed_check_rolls_back_to_the_recorded_commit_and_restarts(world):
    """Each door check gates the ship: when any one fails after the fast-forward (or the restart fails, or /health
    never answers at the new commit), it resets hard to the recorded commit A (three commits behind NEW, so not
    NEW's parent), restarts at A, waits for /health to name A, and exits 1, asking nothing after the failed check
    but /health. A cut session cannot stop the rollback: with no reader on its stderr, a SIGHUP, or a restart that
    reads stdin, it still rolls back to A. The lock is gone after each rollback, and a second ship started during
    the first one's restart refuses with exit 2, changing nothing, while the first rolls back to A."""
    sealed = '{"verdict": "HOLDS", "seal": {"content_hash": "' + "e" * 64 + '"}}'
    health = DOORS[0]
    # why: (the request answered badly, its answer, every request the ship makes, in order)
    failures = {
        "health names another commit": ("GET " + APP + "/health",
                                        {world.NEW: [200, '{"commit": "' + "0" * 40 + '"}'],
                                         "*": [200, '{"commit": "{commit}"}']}, [health, health]),
        "the fallback is not held": ("GET " + APP + "/s/" + FALLBACK, [404, '{"error": "seal not found"}'],
                                     DOORS[:2] + [health]),
        "the fallback does not name the hash": ("GET " + APP + "/s/" + FALLBACK, [200, "<p>a receipt</p>"],
                                                DOORS[:2] + [health]),
        "V3 does not answer": ("GET " + APP + "/s/" + V3, [502, "bad gateway"], DOORS[:3] + [health]),
        "verify was sealed": ("POST " + APP + "/verify?seal=0", [200, sealed], DOORS[:4] + [health]),
        "verify does not hold": ("POST " + APP + "/verify?seal=0", [200, '{"verdict": "BROKEN", "seal": null}'],
                                 DOORS[:4] + [health]),
        "the console lost its ounces": ("POST " + APP + "/console", [200, '{"answer": "a pound"}'],
                                        DOORS[:5] + [health]),
        "find_verifier is gone": ("GET " + APP + "/find_verifier?q=speed+of+light", [404, "not found"],
                                  DOORS + [health]),
        "health never answers at NEW": ("GET " + APP + "/health",
                                        {world.NEW: "down", "*": [200, '{"commit": "{commit}"}']},
                                        [health, health, health]),        # WAIT_TRIES=2 at NEW, then once at A
    }
    for why, (key, answer, asked) in failures.items():
        box = world.clone()
        code, err, calls, restarts = world.ship(box, {**WELL, key: answer})
        assert code == 1 and "rolled back" in err, (why, err)
        assert world.head(box) == world.A != world.git("rev-parse", world.NEW + "~1", cwd=box), why
        assert (box / "app.txt").read_text() == "A\n", why
        assert restarts == [world.NEW, world.A], why
        assert calls == asked, why                       # nothing after the failure but the rollback's /health
        _only_reads(calls)
        assert not _locked(box), why

    v3_down = {**WELL, "GET " + APP + "/s/" + V3: [502, "bad gateway"]}
    cut = {"no one reads its stderr": dict(close_stderr=True),
           "a SIGHUP while it restarts": dict(RESTART_CMD='kill -HUP "$PPID"; ' + RESTART),
           "a restart that reads stdin": dict(RESTART_CMD="cat >/dev/null; " + RESTART)}
    for why, how in cut.items():
        box = world.clone()
        code, _err, calls, restarts = world.ship(box, v3_down, **how)
        assert code == 1, why
        assert world.head(box) == world.A and restarts == [world.NEW, world.A], why
        assert calls == DOORS[:3] + [DOORS[0]] and not _locked(box), why

    box = world.clone()
    code, err, calls, restarts = world.ship(box, FAKE_RESTART_FAILS="1")
    assert code == 1 and "the restart failed" in err and "rolled back" in err, err
    assert world.head(box) == world.A and restarts == [world.NEW, world.A] and calls == [DOORS[0]]
    assert not _locked(box)

    box = world.clone()                     # a second ship during the first one's restart, the first rolling back
    code, err, calls, restarts = world.ship(box, v3_down, RESTART_CMD=OVERLAP)
    second, second_err = world.second()
    assert second == 2 and "another ship holds the lock" in second_err and "recorded HEAD" not in second_err
    assert code == 1 and "rolled back" in err, err
    assert world.head(box) == world.A and restarts == [world.NEW, world.A] and calls == DOORS[:3] + [DOORS[0]]
    assert not _locked(box)


def test_a_failed_rollback_says_so_and_exits_3(world):
    """When the rollback's own restart fails, the checkout is still reset to the recorded commit, and the ship
    says a human is needed and exits 3."""
    box = world.clone()
    code, err, calls, restarts = world.ship(box, {**WELL, "GET " + APP + "/s/" + V3: [500, "no"]},
                                            FAKE_RESTART_FAILS="2")
    assert code == 3 and "ROLLBACK FAILED" in err and world.A in err, err
    assert world.head(box) == world.A and restarts == [world.NEW, world.A] and not _locked(box)

    box = world.clone()                          # restarted at A, but the app still names NEW: not rolled back
    stuck = {**WELL, "GET " + APP + "/health": [200, '{"commit": "' + world.NEW + '"}'],
             "GET " + APP + "/s/" + V3: [500, "no"]}
    code, err, calls, restarts = world.ship(box, stuck)
    assert code == 3 and "ROLLBACK FAILED" in err, err
    assert world.head(box) == world.A and restarts == [world.NEW, world.A] and calls == DOORS[:3] + [DOORS[0]]
    assert not _locked(box)


def test_ship_refuses_to_run_from_inside_the_checkout(world):
    """Run as a file that sits inside the checkout it would rewrite, it refuses with exit 2 before reading
    anything, and before taking the lock: it leaves no lock, and leaves alone a lock another ship holds. The same
    file run from outside the checkout ships, even with a stdin that stays open (as an ssh channel's does) and a
    restart that reads stdin: what it starts reads /dev/null, never its caller's input. A lock left behind refuses
    every ship with exit 2, changing nothing and naming the lock; a ship killed outright (or by a signal) leaves
    its lock, so the next one refuses. The ship never removes a lock it did not take."""
    box = world.clone()
    inside = box / "tools" / "ship.sh"
    inside.parent.mkdir(exist_ok=True)
    inside.write_bytes(SHIP.read_bytes())
    code, err, calls, restarts = world.ship(box, stdin=False, script=inside)
    assert code == 2 and "inside" in err and "bash -s" in err and "took the lock" not in err, err
    assert world.head(box) == world.tracking(box) == world.A and calls == [] and restarts == []
    assert not _locked(box)                                         # refused before the lock: none was taken
    lock = box / ".git" / "ship.lock"
    lock.mkdir()
    (lock / "owner").write_text("pid 4242, started 2026-11-02T00:00:00Z\n", encoding="utf-8")
    code, err, calls, restarts = world.ship(box, stdin=False, script=inside)
    assert code == 2 and "inside" in err and _locked(box), err     # another's lock is left as it was
    code, err, calls, restarts = world.ship(box)
    assert code == 2 and "another ship holds the lock" in err and "pid 4242" in err and "by hand" in err, err
    assert world.head(box) == world.tracking(box) == world.A and calls == [] and restarts == []
    assert (lock / "owner").read_text(encoding="utf-8") == "pid 4242, started 2026-11-02T00:00:00Z\n"
    shutil.rmtree(lock)                                             # removed by hand, as the message says
    code, err, calls, restarts = world.ship(box, stdin=False, script=SHIP)
    assert code == 0 and world.head(box) == world.NEW and not _locked(box), err
    box = world.clone()
    code, err, calls, restarts = world.ship(box, stdin=False, script=SHIP, hold_stdin=True,
                                            RESTART_CMD="cat >/dev/null; " + RESTART)
    assert code == 0, (code, err)
    assert world.head(box) == world.NEW and restarts == [world.NEW] and calls == DOORS and not _locked(box)

    for signal in ("KILL", "TERM"):
        box = world.clone()
        code, err, calls, restarts = world.ship(box, RESTART_CMD=f'kill -{signal} "$PPID"; ' + RESTART)
        assert code != 0 and _locked(box), (signal, code, err)      # killed mid-ship: the lock stays
        code, err, calls, restarts = world.ship(box)
        assert code == 2 and "another ship holds the lock" in err, (signal, err)
        assert calls == [] and restarts == [] and _locked(box), signal


def test_ship_is_lf_and_gitattributes_pins_it():
    """tools/ship.sh holds no carriage return (bash would read each one as part of the line), and .gitattributes
    pins it to LF on every checkout, Windows' included."""
    data = SHIP.read_bytes()
    assert data.startswith(b"#!/usr/bin/env bash\n") and b"\r" not in data
    lines = (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
    assert "tools/ship.sh text eol=lf" in lines
    if shutil.which("git") and (ROOT / ".git").exists():
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        out = subprocess.run(["git", "check-attr", "eol", "--", "tools/ship.sh"], cwd=ROOT, env=env,
                             capture_output=True, text=True, check=True).stdout.strip()
        assert out == "tools/ship.sh: eol: lf"
