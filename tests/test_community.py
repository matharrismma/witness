"""The Community — read the mesh overview, the map (gated without a node), and the groups."""
import json
import os

import pytest

from nh_org import community
from nh_org.core_client import CoreClient, RecordedTransport

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "fixtures", "community_recorded.json")

pytestmark = pytest.mark.skipif(not os.path.exists(FIX),
                                reason="run tools/record_community.py first")


@pytest.fixture()
def client():
    return CoreClient(RecordedTransport(json.load(open(FIX, encoding="utf-8"))))


def test_overview_describes_the_fellowship(client):
    out = community.overview(client=client)
    assert out.get("duty") and out.get("purpose"), out


def test_the_map_is_gated_without_a_node(client):
    """The mesh is hidden: with no fingerprint the core returns the invitation, not the map."""
    out = community.map("", client=client)
    assert out.get("gated") or out.get("confession") or out.get("message"), out


def test_groups_lists_the_study_groups(client):
    out = community.groups(client=client)
    assert "groups" in out and "total" in out, out


def test_write_doors_are_named_not_composable():
    from nh_org import core_client
    for d in community.COMMUNITY_WRITE_DOORS:
        assert d not in core_client.CORE_DOORS, f"{d} is a signed/consequential write; not composable"


@pytest.mark.skipif(os.environ.get("NH_CORE_LIVE") != "1", reason="set NH_CORE_LIVE=1 to hit the real core")
def test_live_community_reads():
    assert community.overview().get("duty")
    assert "total" in community.groups()
