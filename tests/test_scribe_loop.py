"""The Scribe loop, proven against recorded core verdicts — consensus is not truth.

The finding the prototype recorded (2026-10-20): five Claude writers agreed to 5-6 significant
figures (tiny spread) on pass 1, yet the core's deterministic recompute still caught a wrong claim
that consensus could not see. After one feedback pass, zero broken. These tests replay the core's
recorded verdicts (offline, deterministic) and assert exactly that shape.

A live smoke test (test_live_*) hits the real core; it skips unless NH_CORE_LIVE=1.
"""
import json
import os
import shutil

import pytest

from nh_org.core_client import CoreClient, RecordedTransport
from nh_org.scribe import orchestrate

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "fixtures")
RECORDING_PATH = os.path.join(FIX, "core_recorded.json")

pytestmark = pytest.mark.skipif(
    not os.path.exists(RECORDING_PATH),
    reason="run tools/record_core.py first to capture the core's verdicts")


@pytest.fixture()
def client():
    rec = json.load(open(RECORDING_PATH, encoding="utf-8"))
    return CoreClient(RecordedTransport(rec))


@pytest.fixture()
def root(tmp_path):
    shutil.copytree(os.path.join(FIX, "passes"), tmp_path / "passes")
    return str(tmp_path)


def test_the_engine_catches_what_consensus_missed(client, root):
    """Pass 1: writers agree closely (small spread) but the core flags at least one wrong claim."""
    rep = orchestrate.score(1, root=root, client=client)
    assert rep["broken_total"] >= 1, "the recorded pass-1 drafts had a wrong claim the core should flag"
    assert rep["spread"] < 0.05, f"writers were supposed to agree closely; spread={rep['spread']}"
    # the datum overrides the crowd: a claim can be unanimous-looking and still BROKEN
    broke = [a for a, b in rep["broken"].items() if b]
    assert broke, "no draft was marked broken, yet broken_total>=1 — report is inconsistent"


def test_the_second_pass_is_clean(client, root):
    """After one feedback pass the writers resolved the mismatch: zero broken."""
    rep = orchestrate.score(2, root=root, client=client)
    assert rep["broken_total"] == 0, f"pass 2 still has broken claims: {rep['broken']}"


def test_the_center_draft_verifies_and_the_dry_run_does_not_write_a_seal(client, root):
    orchestrate.score(2, root=root, client=client)
    ledger, draft = orchestrate.final(2, root=root, client=client, seal=False)
    assert ledger["verdict"] == "HOLDS", ledger
    assert ledger["sealed"] is False and not ledger["seal"], "a dry run must not mint a receipt"
    assert "[AUTHORITY]" not in draft and "Northwest Georgia" in draft, "context must be reapplied to the final"


@pytest.mark.skipif(os.environ.get("NH_CORE_LIVE") != "1", reason="set NH_CORE_LIVE=1 to hit the real core")
def test_live_core_flags_a_wrong_number():
    c = CoreClient()
    res = c.verify([{"id": "re", "domain": "mathematics", "spec": {"mode": "numeric",
                     "params": {"numeric_expr": "12245000*0.045/12", "claimed_value": 50000, "rel_tol": 1e-3}}}])
    assert res["verdict"] == "BROKEN" and res["trail"][0]["status"] == "MISMATCH"
