import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from canon.table import Table, parse_ref  # noqa: E402
from canon import synth, evaluate as E, verifier  # noqa: E402

if not (ROOT / "data" / "web.jsonl").exists():
    pytest.skip("canon data not built (python -m canon build …)", allow_module_level=True)


@pytest.fixture(scope="module")
def t():
    tb = Table.load(ROOT / "data")
    verifier._TABLE = tb
    return tb


def _st(r):   # VerifierResult with the engine installed, plain dict without it
    return getattr(r, "status", None) or r["status"]


def _d(r):
    return getattr(r, "data", None) or r["data"]


J316 = "For God so loved the world, that he gave his only born Son, that whoever believes in him should not perish, but have eternal life."


def test_table_is_the_whole_canon(t):
    assert len(t.rows) == 31098 and len({r["book"] for r in t.rows}) == 66
    assert t.get("John", 3, 16)["text"] == J316
    assert t.find_text(J316.lower().replace(",", "")) is t.get("John", 3, 16)   # normalised lookup
    assert t.find_text("For God so loved the world, that he gave his only begotten Son") is None
    near, d = t.nearest("For God so loved the world, that he gave his only begotten Son, that whosoever believeth in him should not perish, but have everlasting life.")
    assert (near["book"], near["chapter"], near["verse"]) == ("John", 3, 16) and d == 4
    assert t.find_phrase("my shepherd I shall lack nothing")[0]["book"] == "Psalms"
    assert t.xrefs("John", 3, 16)[0][:3] == ("Romans", 5, 8)
    assert parse_ref("1 Cor 13:4") == ("1 Corinthians", 13, 4) and parse_ref("Hezekiah 3:5") is None


def test_verifier_is_exact_and_names_the_counterexample(t):
    ok = verifier.verify_quote({"quote": J316, "ref": "John 3:16"})
    assert _st(ok) == "CONFIRMED"
    bad = verifier.verify_quote({"quote": J316.replace("born", "begotten"), "ref": "John 3:16"})
    assert _st(bad) == "MISMATCH" and _d(bad)["counterexample"]["nearest"] == "John 3:16" and _d(bad)["distance"] == 1
    wrong = verifier.verify_quote({"quote": J316, "ref": "John 3:17"})
    assert _st(wrong) == "MISMATCH" and _d(wrong)["counterexample"]["what"] == "ref"
    assert _st(verifier.verify_ref({"claimed_ref": "Psalm 151:1"})) == "MISMATCH"
    assert _st(verifier.verify_xref({"claimed_xref": {"from": "John 3:16", "to": "Romans 5:8"}})) == "CONFIRMED"
    assert verifier.STRATUM == "pure"


def test_synth_examples_are_verified_and_filter_catches_fabrication(t):
    ex = list(synth.generate(t, 60, seed=3))
    assert len(ex) == 60 and all(e["checked"]["quotes"] >= 0 for e in ex)
    assert {e["family"] for e in ex} >= {"lookup", "correct", "refuse"}
    fab = {"messages": [{"role": "user", "content": "x"}, {"role": "assistant", "content": "John 3:16 (WEB): For God so loved the world that he gave his only begotten Son."}]}
    assert synth.check_example(t, fab)[0] is False
    mis = {"messages": [{"role": "user", "content": "x"}, {"role": "assistant", "content": f"John 3:17 (WEB): {J316}"}]}
    assert synth.check_example(t, mis)[1]["reason"].startswith("attributed to")
    smuggled = {"messages": [{"role": "user", "content": "x"}, {"role": "assistant", "content": "As it says, In the beginning, God created the heavens and the earth."}]}
    assert synth.check_example(t, smuggled)[1]["reason"] == "uncited scripture in prose"


def test_eval_oracle_clean_scrambler_caught(t):
    ex = list(synth.generate(t, 40, seed=5))
    clean = E.evaluate(t, E.oracle_from(ex), ex)
    assert clean["total"]["clean"] == 40 and clean["total"]["counterexamples"] == 0
    caught = E.evaluate(t, E.scrambler_from(ex), ex)
    cited = sum(1 for e in ex if e["checked"]["quotes"])
    assert caught["counterexample_kinds"].get("misquote", 0) >= cited * 0.9
    assert caught["total"]["posterior_fail_rate"]["mean"] > 0.5


def test_posterior_matches_closed_form():
    p = E.beta_posterior(0, 1796)
    assert abs(p["upper95"] - (1 - 0.05 ** (1 / 1797))) < 1e-6 and abs(p["mean"] - 1 / 1798) < 1e-9
    assert abs(E.betainc(2, 3, 0.5) - 0.6875) < 1e-9


def test_train_dry_run_refuses_unverified(tmp_path, t):
    rows = list(synth.generate(t, 10, seed=9))
    p = tmp_path / "ok.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows))
    from canon import train
    assert train.main(["--data", str(p), "--out", str(tmp_path / "o"), "--dry-run"]) == 0
    bad = tmp_path / "bad.jsonl"
    bad.write_text(json.dumps({"family": "lookup", "messages": rows[0]["messages"]}))
    with pytest.raises(SystemExit):
        train.main(["--data", str(bad), "--out", str(tmp_path / "o"), "--dry-run"])
