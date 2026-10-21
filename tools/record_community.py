"""Record the core's community read-door responses for the Community fixtures (read-only).

    NH_CORE_URL=https://api.narrowhighway.com python tools/record_community.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nh_org.core_client import CoreClient, RecordingTransport  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "..", "tests", "fixtures", "community_recorded.json")

rt = RecordingTransport(delay=0.3)
client = CoreClient(rt)
client.mesh()           # GET /mesh
client.mesh_map("")     # GET /mesh/map (no fp -> the gated invitation)
client.groups()         # GET /groups

json.dump(rt.recording, open(OUT, "w", encoding="utf-8"), indent=0, sort_keys=True)
print(f"recorded {len(rt.recording)} community responses -> {OUT}")
