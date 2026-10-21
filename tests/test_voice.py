"""The voice (RADIO) — the core /speak ceiling, degrading to the floor, never fabricated.

With ElevenLabs credits the core returns audio/mpeg; without them it returns its 503 floor and the
app reports spoken=False so the caller drops to the browser voice or plain text.
"""
import os

import pytest

from nh_org import console
from nh_org.core_client import CoreClient


class _FakeRaw:
    """A transport whose post_raw returns a fixed (status, body, mime)."""

    def __init__(self, status, body=b"", mime="audio/mpeg"):
        self._r = (status, body, mime)

    def post_raw(self, path, body, query=""):
        assert path == "/speak" and "text" in body
        return self._r


class _JsonOnly:
    """A transport with no post_raw (like the recorded JSON transport) — must yield the floor."""

    def post(self, *a, **k):
        return {}


def test_voice_reports_the_floor_when_the_ceiling_is_unavailable():
    out = CoreClient(_FakeRaw(503)).speak("peace I leave with you")
    assert out["spoken"] is False and out["floor"] is True and out["audio"] is None


def test_voice_speaks_when_the_ceiling_is_available():
    out = console.speak("peace I leave with you",
                        client=CoreClient(_FakeRaw(200, b"ID3\x04fake-mp3-bytes", "audio/mpeg")))
    assert out["spoken"] is True and out["audio"] and out["mime"] == "audio/mpeg"


def test_a_json_only_transport_degrades_to_the_floor():
    assert CoreClient(_JsonOnly()).speak("x")["floor"] is True


@pytest.mark.skipif(os.environ.get("NH_CORE_LIVE") != "1", reason="set NH_CORE_LIVE=1 to hit the real core")
def test_live_speak_is_honest_floor_or_audio():
    out = console.speak("Narrow Highway voice check.")
    assert out["spoken"] in (True, False)
    if out["spoken"]:
        assert out["audio"] and out["mime"]
    else:
        assert out["floor"] and out["audio"] is None
