"""The Record — the witness's testimony, read and composed from the core (V3 migration step 4).

"The RECORD lives on .org — seals and badges. The witness keeps the testimony." This surface reads
and composes the core's record doors; it holds no record of its own and signs nothing.

READ / COMPOSE (here, safe):
- `fetch(content_hash)`  → the sealed receipt, re-checkable            (GET /seal)
- `recent()`            → the ledger tally                            (GET /seals)
- `badge(seal_hashes)`  → compose sealed checks into the EVIDENCE badge, issued UNSIGNED (POST /badges)

SIGNED WRITES (a declared seam — NOT performed here): a profession of faith
(POST /mesh/node {public_key, confession, confession_sig}), a self-attestation (POST /self-attest),
and binding a badge to an identity (sign its content_hash, POST /attest) all require the HOLDER'S OWN
key and signature, born and kept on their device (the core's identity_create). The app never holds a
private key, never signs for anyone, and never rolls crypto. These cross the boundary only as the
holder's own signed request with their explicit authorization — see docs/RECORD.md.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .core_client import CoreClient

# The gated, signed doors — named so the seam is explicit, never silently skipped. Not in CORE_DOORS
# until the identity/signing model lands; the app composes them only as the holder's signed request.
SIGNED_WRITE_DOORS = ("/mesh/node", "/self-attest", "/attest")


def fetch(content_hash: str, *, client: Optional[CoreClient] = None) -> Optional[Dict[str, Any]]:
    """The sealed receipt for a hash — how the witness app re-reads the testimony. None if absent."""
    return (client or CoreClient()).seal(content_hash)


def recent(*, limit: int = 20, client: Optional[CoreClient] = None) -> Dict[str, Any]:
    """The ledger tally of sealed records."""
    return (client or CoreClient()).seals(limit=limit)


def badge(seal_hashes: List[str], *, title: str = "",
          client: Optional[CoreClient] = None) -> Dict[str, Any]:
    """Compose sealed checks into the evidence badge (unsigned — the evidence is the badge)."""
    return (client or CoreClient()).badge(seal_hashes, title=title)
