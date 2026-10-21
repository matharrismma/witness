"""The Console composes the core's /ask door — found + verified, never generated.

Replays recorded core /ask responses (offline, deterministic). A live smoke test hits the real core
when NH_CORE_LIVE=1.
"""
import json
import os

import pytest

from nh_org import console
from nh_org.core_client import CoreClient, RecordedTransport

HERE = os.path.dirname(os.path.abspath(__file__))
RECORDING = os.path.join(HERE, "fixtures", "console_recorded.json")

pytestmark = pytest.mark.skipif(
    not os.path.exists(RECORDING),
    reason="run tools/record_console.py first to capture the core's /ask responses")


@pytest.fixture()
def client():
    return CoreClient(RecordedTransport(json.load(open(RECORDING, encoding="utf-8"))))


def test_the_console_answers_from_the_core_and_never_generates(client):
    out = console.dispatch("how many ounces in a pound", client=client)
    assert out["answer"], "the Console returned no answer from the core"
    assert out["generated"] is False, "the Console must never present generated content"
    assert out["next_step"], "every Console answer ends with one next step (the house contract)"


def test_the_enrichments_are_stubbed_until_wired_app_side(client):
    out = console.dispatch("what is the boiling point of water in celsius", client=client)
    # voice (RADIO) and the witness cloud are app-side features that land incrementally; until then
    # they are explicitly absent, not faked.
    assert out["voice"] is None and out["cloud"] is None


@pytest.mark.skipif(os.environ.get("NH_CORE_LIVE") != "1", reason="set NH_CORE_LIVE=1 to hit the real core")
def test_live_console_answers_a_lookup():
    out = console.dispatch("how many ounces in a pound")
    assert out["answer"] and out["generated"] is False
