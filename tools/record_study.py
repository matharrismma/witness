"""Record the core's study/coach read-door responses for the Study fixtures (read-only).

    NH_CORE_URL=https://api.narrowhighway.com python tools/record_study.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nh_org.core_client import CoreClient, RecordingTransport  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "..", "tests", "fixtures", "study_recorded.json")

rt = RecordingTransport(delay=0.3)
client = CoreClient(rt)
client.teachings()
client.decks()
client.coach_overview()
client.coach_next()
client.playbook()

json.dump(rt.recording, open(OUT, "w", encoding="utf-8"), indent=0, sort_keys=True)
print(f"recorded {len(rt.recording)} study responses -> {OUT}")
