"""The Console — the .org app's unified front door (V3: moved out of the core engine).

The Console is a COMPOSED EXPERIENCE, not a verifier: speak or type anything → the core finds +
verifies + cites (never generates) → the answer is rendered with its trail and one next step. It
composes the core's `/ask` door over HTTP and holds no verifier and no corpus of its own.

Why it moved: in the core the Console was welded to the ancillary layer — the cloned voice (RADIO),
the public-domain witness cloud, the coach/shepherd weave, the book render, keep/scribe. Those are
app-side and land here incrementally (docs/MIGRATION.md). The verification spine stays the core's,
reached through nh_org.core_client. This module is that spine's composition; the enrichments are
stubbed (voice/cloud = None) until each is wired app-side.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from ..core_client import CoreClient


def dispatch(text: str, *, client: Optional[CoreClient] = None,
             thread_id: Optional[str] = None, gate_open: bool = False) -> Dict[str, Any]:
    """Take one ask, compose the core's /ask door, and shape the Console front-door payload.

    `gate_open` follows the surface: the .org/witness face opens the Gate (the Word, the shepherd
    step and the witness cloud come woven in); the .com/secular face leaves it closed. Every field
    here is the core's — found, verified, cited — never generated. The only piece not wired is the
    cloned voice (audio via the core /speak door), which is gated on ElevenLabs credits."""
    client = client or CoreClient()
    r = client.ask(text, thread_id=thread_id, gate_open=gate_open)
    house = r.get("house") or {}
    verify = r.get("verify") if isinstance(r.get("verify"), dict) else None
    path = r.get("path") if isinstance(r.get("path"), dict) else None
    return {
        "answer": r.get("message"),
        "kind": r.get("kind"),
        "verify": verify,
        "trail": (verify or {}).get("trail"),
        "lead": r.get("lead"),                     # the card the situation is an instance of
        # enrichments the core weaves when the Gate is open — found/verified, never generated:
        "word": (path or {}).get("anchor"),        # the verse, verbatim + cited ({ref, text})
        "coach": ({"framing": path.get("framing"), "step": path.get("step")} if path else None),
        "cloud": r.get("cloud"),                   # the public-domain witness cloud fit to the theme
        "next_step": house.get("next_step"),
        "gate_open": r.get("gate_open"),
        "thread_id": r.get("thread_id"),
        "generated": r.get("generated", False),
        # RADIO: the answer spoken in the cloned voice via the core /speak door — a declared seam,
        # gated on ElevenLabs credits + explicit go, so not wired here (docs/MIGRATION.md).
        "voice": None,
    }


def _main(argv):
    import json
    if not argv:
        print('usage: python -m nh_org.console "<what you bring>"')
        return 2
    from ..core_client import CoreUnavailable
    try:
        print(json.dumps(dispatch(" ".join(argv)), indent=1))
    except CoreUnavailable as e:
        print(f"core unavailable — nothing fabricated: {e}")
        return 3
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(_main(sys.argv[1:]))
