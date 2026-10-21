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


def test_the_gate_open_console_weaves_the_word_and_the_witness_cloud(client):
    """On the witness face the Gate is open: the core weaves the Word (verbatim + cited), the
    shepherd step and the public-domain witness cloud — the Console surfaces them, never generated."""
    out = console.dispatch("what does scripture say about honest work", client=client, gate_open=True)
    assert out["generated"] is False
    assert out["word"] and out["word"].get("ref") and out["word"].get("text"), "the Word came back empty"
    assert out["coach"] and out["coach"].get("step"), "no shepherd step on a Gate-open ask"
    cloud = out["cloud"] or {}
    assert cloud.get("witnesses"), "the witness cloud is empty on a Gate-open ask"


def test_voice_is_a_declared_gated_seam_not_faked(client):
    """The cloned voice (audio) is gated on ElevenLabs credits, so it stays an explicit None — the
    Console never fakes audio or a voice it did not actually synthesize."""
    out = console.dispatch("what does scripture say about honest work", client=client, gate_open=True)
    assert out["voice"] is None


def test_secular_console_leaves_the_gate_closed(client):
    """The .com/secular face does not open the Gate: a plain lookup answers without the Word woven in."""
    out = console.dispatch("how many ounces in a pound", client=client)
    assert out["answer"] and out["generated"] is False
    assert out["word"] is None


@pytest.mark.skipif(os.environ.get("NH_CORE_LIVE") != "1", reason="set NH_CORE_LIVE=1 to hit the real core")
def test_live_console_answers_a_lookup():
    out = console.dispatch("how many ounces in a pound")
    assert out["answer"] and out["generated"] is False
