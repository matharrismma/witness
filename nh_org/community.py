"""The Community — the Fellowship Mesh and the study groups, read from the core (V3 migration step 5).

The witness app can SHOW the fellowship: the mesh overview (what it is and its duty), the map around
a node, and the study groups. It composes the core's read doors and keeps no social state of its own.

READ (here, safe):
- `overview()`          → the Fellowship Mesh doctrine                 (GET /mesh)
- `map(fp="", hops=2)`  → the map around a node, or the gated invite when no node   (GET /mesh/map)
- `groups()`            → the study groups, {groups, total}            (GET /groups)

SIGNED / CONSEQUENTIAL WRITES (a declared seam — NOT performed here): joining the fellowship
(POST /mesh/node), posting to the mesh (POST /mesh/post), leaving a blessing on a door
(POST /mesh/door), linking, tending, inviting, redeeming (POST /mesh/link|tend|invite|redeem), and
creating/joining/contributing to a group (POST /groups, /group/join, /group/contribute) are the
member's OWN acts — most signed with their device key, all consequential and outward-facing. The app
never signs for anyone and never posts on anyone's behalf: these cross the boundary only as the
member's own authorized (and, where required, signed) request. See docs/COMMUNITY.md.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from .core_client import CoreClient

# The gated write doors — named so the seam is explicit; deliberately NOT in CORE_DOORS.
COMMUNITY_WRITE_DOORS = ("/mesh/node", "/mesh/post", "/mesh/door", "/mesh/link", "/mesh/tend",
                         "/mesh/invite", "/mesh/redeem", "/group/join", "/group/contribute")


def overview(*, client: Optional[CoreClient] = None) -> Dict[str, Any]:
    """The Fellowship Mesh — what it is, its duty, its roles."""
    return (client or CoreClient()).mesh()


def map(fp: str = "", *, hops: int = 2, client: Optional[CoreClient] = None) -> Dict[str, Any]:
    """The map around a node; without a node the core returns the gated invitation, not the map."""
    return (client or CoreClient()).mesh_map(fp, hops=hops)


def groups(*, client: Optional[CoreClient] = None) -> Dict[str, Any]:
    """The study groups — {groups, total}."""
    return (client or CoreClient()).groups()
