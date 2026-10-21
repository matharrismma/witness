"""Record the live core's /ask responses for the Console fixtures, so the test replays offline.

Read-only (/ask finds + verifies; this sends only benign, de-identified questions). Run once:

    NH_CORE_URL=https://api.narrowhighway.com python tools/record_console.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nh_org import console  # noqa: E402
from nh_org.core_client import CoreClient, RecordingTransport  # noqa: E402

# (question, gate_open) — the closed Gate is the .com/secular case, the open Gate the .org/witness case
QUESTIONS = [
    ("how many ounces in a pound", False),
    ("what is the boiling point of water in celsius", False),
    ("what does scripture say about honest work", True),
]
OUT = os.path.join(os.path.dirname(__file__), "..", "tests", "fixtures", "console_recorded.json")

rt = RecordingTransport()
client = CoreClient(rt)
for q, gate in QUESTIONS:
    console.dispatch(q, client=client, gate_open=gate)

json.dump(rt.recording, open(OUT, "w", encoding="utf-8"), indent=0, sort_keys=True)
print(f"recorded {len(rt.recording)} /ask responses -> {OUT}")
