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
             thread_id: Optional[str] = None) -> Dict[str, Any]:
    """Take one ask, compose the core's /ask door, and shape the Console front-door payload."""
    client = client or CoreClient()
    r = client.ask(text, thread_id=thread_id)
    house = r.get("house") or {}
    verify = r.get("verify") if isinstance(r.get("verify"), dict) else None
    return {
        "answer": r.get("message"),
        "kind": r.get("kind"),
        "verify": verify,
        "trail": (verify or {}).get("trail"),
        "next_step": house.get("next_step"),
        "gate_open": r.get("gate_open"),
        "thread_id": r.get("thread_id"),
        "generated": r.get("generated", False),
        # app-side enrichments, staged (docs/MIGRATION.md) — never generated, always found/verified:
        "voice": None,   # RADIO: the answer spoken in the cloned voice (box-side personal content)
        "cloud": None,   # the public-domain witness cloud fit to the theme
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
