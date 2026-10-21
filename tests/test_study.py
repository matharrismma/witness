"""Study & coach — the teaching queue, decks, the coach's overview/next, playbook."""
import json
import os

import pytest

from nh_org import study
from nh_org.core_client import CoreClient, RecordedTransport

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "fixtures", "study_recorded.json")

pytestmark = pytest.mark.skipif(not os.path.exists(FIX), reason="run tools/record_study.py first")


@pytest.fixture()
def client():
    return CoreClient(RecordedTransport(json.load(open(FIX, encoding="utf-8"))))


def test_teachings_are_grouped(client):
    out = study.teachings(client=client)
    assert out.get("groups") and out.get("total"), out


def test_decks_list(client):
    assert "decks" in study.decks(client=client)


def test_coach_overview_and_next(client):
    ov = study.coach_overview(client=client)
    assert ov.get("subject") and (ov.get("units") or ov.get("tracks")), ov
    nx = study.coach_next(client=client)
    assert nx.get("subject") and "unit" in nx, nx


def test_playbook_reads(client):
    assert study.playbook(client=client).get("ok") is not None


def test_write_doors_are_named_not_composable():
    from nh_org import core_client
    for d in study.STUDY_WRITE_DOORS:
        assert d not in core_client.CORE_DOORS, f"{d} is a write; not composable"


@pytest.mark.skipif(os.environ.get("NH_CORE_LIVE") != "1", reason="set NH_CORE_LIVE=1 to hit the real core")
def test_live_study_reads():
    assert study.teachings().get("total")
    assert "decks" in study.decks()
