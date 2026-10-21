"""Record the live core's /verify responses for the Scribe fixtures, so tests replay offline.

Read-only against the core (seal=0 throughout — the final() call here is a dry run). Run once to
(re)generate tests/fixtures/core_recorded.json after the fixtures or packets change:

    NH_CORE_URL=https://api.narrowhighway.com python tools/record_core.py

The recording is keyed by nh_org.core_client.request_key, so the test's RecordedTransport returns
exactly what the core said for each step.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nh_org.core_client import CoreClient, RecordingTransport  # noqa: E402
from nh_org.scribe import orchestrate  # noqa: E402

ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "tests", "fixtures")
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "core_recorded.json")

rt = RecordingTransport()
client = CoreClient(rt)
for n in (1, 2):
    orchestrate.score(n, root=ROOT, client=client)
orchestrate.final(2, root=ROOT, client=client, seal=False)  # dry run — captures the final verify, no write

json.dump(rt.recording, open(OUT, "w", encoding="utf-8"), indent=0, sort_keys=True)
print(f"recorded {len(rt.recording)} core responses -> {OUT}")
