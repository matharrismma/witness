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


def test_the_only_core_door_is_verify():
    """core_client talks to exactly one core path. A second path is a new coupling to review."""
    import inspect

    from nh_org import core_client
    src = inspect.getsource(core_client)
    paths = sorted(set(p for p in ("/verify",) if p in src))
    assert paths == ["/verify"], paths
    assert "/attach" not in src and "/seal" not in src, "sealing goes through /verify?seal=1, not a new path"
