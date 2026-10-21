"""Record the core's record-door responses for the Record fixtures.

Mints ONE benign receipt (a true arithmetic claim via /verify?seal=1 — the engine's normal
re-checkable receipt, PII-free), then reads it back (GET /seal), the ledger tally (GET /seals), and
composes it into a badge (POST /badges). Writes the mint's hash to the fixture so the test knows it.

    NH_CORE_URL=https://api.narrowhighway.com python tools/record_ledger.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nh_org.core_client import CoreClient, RecordingTransport  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "..", "tests", "fixtures", "ledger_recorded.json")

rt = RecordingTransport(delay=0.3)
client = CoreClient(rt)

# mint one benign receipt (a true arithmetic claim) and take its content hash
minted = client.verify([{"id": "re", "domain": "mathematics", "spec": {"mode": "numeric",
                         "params": {"numeric_expr": "16", "claimed_value": 16, "rel_tol": 1e-9}}}], seal=True)
seal = CoreClient.seal_of(minted)
h = seal.get("content_hash")
assert h, f"mint did not return a content_hash: {seal}"

client.seal(h)                 # GET /seal?hash=
client.seals(limit=3)          # GET /seals
client.badge([h], title="arithmetic, checked")  # POST /badges

out = {"minted_hash": h, "recording": rt.recording}
json.dump(out, open(OUT, "w", encoding="utf-8"), indent=0, sort_keys=True)
print(f"minted {h[:16]}…; recorded {len(rt.recording)} record responses -> {OUT}")
