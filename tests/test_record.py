"""The Record — fetch a sealed receipt, read the ledger tally, compose a badge; signed writes seam."""
import json
import os

import pytest

from nh_org import record
from nh_org.core_client import CoreClient, CoreUnavailable, RecordedTransport

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "fixtures", "ledger_recorded.json")

pytestmark = pytest.mark.skipif(not os.path.exists(FIX),
                                reason="run tools/record_ledger.py first to mint+capture a seal")


@pytest.fixture()
def recorded():
    return json.load(open(FIX, encoding="utf-8"))


@pytest.fixture()
def client(recorded):
    return CoreClient(RecordedTransport(recorded["recording"]))


def test_fetch_reads_the_sealed_receipt(client, recorded):
    rec = record.fetch(recorded["minted_hash"], client=client)
    assert rec, "the minted seal did not read back"


def test_recent_returns_the_ledger_tally(client):
    out = record.recent(limit=3, client=client)
    assert isinstance(out.get("seals"), dict) and out["seals"], out


def test_badge_composes_the_sealed_evidence(client, recorded):
    out = record.badge([recorded["minted_hash"]], title="arithmetic, checked", client=client)
    assert int(out.get("checks", 0)) >= 1, out


class _Missing:
    def get(self, path, query=""):
        raise CoreUnavailable(f"{path}: HTTP Error 404: Not Found")


def test_a_missing_seal_is_none_not_an_error():
    assert record.fetch("deadbeef" * 8, client=CoreClient(_Missing())) is None


def test_the_signed_write_doors_are_named_not_called():
    """The gated doors are documented, not in the composable allowlist — the app never signs."""
    from nh_org import core_client
    for d in record.SIGNED_WRITE_DOORS:
        assert d not in core_client.CORE_DOORS, f"{d} is a signed write; it must not be composable"


@pytest.mark.skipif(os.environ.get("NH_CORE_LIVE") != "1", reason="set NH_CORE_LIVE=1 to hit the real core")
def test_live_fetch_round_trips(recorded):
    rec = record.fetch(recorded["minted_hash"])
    assert rec, "the minted seal is not re-checkable live"
