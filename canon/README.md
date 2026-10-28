# canon — a small model that looks up and cites, and the hash table it stands on

Nothing is generated: found, verified, cited, sealed. The Bible's text lives in a hash table, never in a
model's weights, and a model trained here learns one skill — look up, then cite — which is exactly the skill a
1.58-bit model can hold.

| piece | what |
|---|---|
| `canon/usfm.py` | reads the World English Bible (public domain, ebible.org USFM with inline Strong's tags) |
| `canon/table.py` | every verse a bucket: `sha256({translation, book, chapter, verse, normalised text})`; exact lookup, phrase containment, nearest-verse for misses, cross-references (openbible.info, CC-BY), Strong's index; one root commitment over the whole canon |
| `canon/verifier.py` | the `scripture` domain for Concordance (entry point `concordance.verifiers`), stratum **pure**: `quote` (hash; a miss names the nearest verse and the word distance), `claimed_ref`, `claimed_strong`, `claimed_xref` |
| `canon/synth.py` | training trajectories (question → tool calls → verbatim results → cited answer) in seven families; **every quote in every example is re-checked by hash and the example is dropped on any failure** |
| `canon/evaluate.py` | the inverted eval: counterexample kinds (misquote, misattribution, uncited scripture, cited without retrieval, answered the unanswerable) with Beta posteriors; an oracle (must score clean) and a scrambler (must be caught) prove the harness |
| `canon/train.py` | LoRA SFT, default base `microsoft/bitnet-b1.58-2B-4T-bf16` (ternary at serve time via bitnet.cpp); refuses data without the verifier's stamp |
| `canon/serve.py` | the four tools over HTTP — what the model calls at inference |

```bash
pip install -e .                       # + "[engine]" to verify through Concordance, "[train]" on a GPU box
python -m canon build <eng-web_usfm/> <cross_references.txt>     # → data/ (31,098 verses, 66 books)
python -m canon synth 20000 data/train.jsonl --seed 42           # 20k verified trajectories
python -m canon eval data/eval.jsonl --oracle                     # 1000/1000 clean
python -m canon eval data/eval.jsonl --scrambled                  # 0/1606 cited lines survive
python -m canon.train --data data/train.jsonl --out runs/canon-bitnet   # GPU
```

## Measured (2026-10-28)

- Table: 31,098 verses, 66 books, 28,752 cross-reference sources; root `dd645c66…`.
- Verifier through the Concordance engine: verbatim John 3:16 → HOLDS (pure); KJV wording → BROKEN, nearest John 3:16 at 4 word edits; right verse wrong ref → BROKEN naming the ref; Psalm 151:1 → BROKEN; John 3:16 → Romans 5:8 recorded (991 votes).
- Synth: 20,000 trajectories written, ~1% dropped by the hash filter (fragments that were ambiguous, swaps that landed on a different verse).
- Eval harness: oracle 1000/1000 clean (posterior next-failure mean 0.1%, 95% upper 0.3%); scrambler caught on every cited line.

## What the model is and is not

It is a router with a conscience: it decides which tool to call and quotes only what came back. It is not a
source of scripture. A 1.58-bit model is adequate for that because the precision lives in the table. The
eval does not ask whether answers sound right; it counts how often they are caught, and reports the
posterior on being caught next time.

## Limits, stated

- The Strong's tagging is the WEB's own and is partial (e.g. "loved" in John 3:16 carries no tag).
- One translation (WEB). Other public-domain texts are a `translation` field away; nothing here assumes English.
- `train.py` has not been run on a GPU in this checkout; the data and the harness have.
