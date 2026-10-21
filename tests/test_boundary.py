"""The V3 boundary, pinned: the .org app NEVER imports the core.

If this fails, someone reached across the split and imported `concordance` directly instead of
calling the core over HTTP — the one thing V3 exists to prevent. The app must depend on the core
only through nh_org.core_client's HTTP door.
"""
import importlib
import sys


def test_the_org_app_never_imports_the_core():
    for m in ("nh_org", "nh_org.core_client", "nh_org.scribe",
              "nh_org.scribe.packets", "nh_org.scribe.orchestrate"):
        importlib.import_module(m)
    leaked = sorted(m for m in sys.modules if m == "concordance" or m.startswith("concordance."))
    assert not leaked, f"the .org app imported core modules directly: {leaked}"


def test_core_doors_are_a_reviewed_allowlist():
    """The app may call only the core doors on the reviewed allowlist, and reaches them only through
    core_client (which posts to `self.t.post("/...")`). A new door is a deliberate addition here, not
    a quiet new coupling; anything off the list — e.g. a write door like /attach — must not appear."""
    import inspect
    import re

    from nh_org import core_client
    src = inspect.getsource(core_client)
    called = sorted(set(re.findall(r'\.post\(\s*"(/[a-z_]+)"', src)))
    assert called, "core_client makes no core call — did the client change shape?"
    off_list = [p for p in called if p not in core_client.CORE_DOORS]
    assert not off_list, f"core_client calls doors not on the reviewed allowlist CORE_DOORS: {off_list}"
    assert "/attach" not in src, "sealing goes through /verify?seal=1, never a separate write door"
