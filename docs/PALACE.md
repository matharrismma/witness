# The Palace — keep, as a memory palace

The Console's "keep" (`nh_org/palace.py`). Three structures do the work, as Matt put it: *sorting
algorithms, tensors and memory palaces can assist.*

- **Memory palace (method of loci).** Every kept exchange is placed at a **locus** `(room, position)`
  you can walk back to. The *room* is the exchange's kind or dominant theme; the *position* is its
  order within that room. You recall by walking to a place, not by scanning a list.
- **Tensor.** The loci are a 2-axis grid, `room × position`. `shape()` reports its extent
  (`rooms`, `max_positions`, `kept`); `walk(room)` fixes one axis and reads along the other.
- **Sort.** `recall(cue)` ranks every locus by relevance — token overlap normalized by record size,
  so a long record cannot dominate — with recency as the tiebreak, and returns the top of that sort.

## What it keeps

Only what the core already found and verified: the ask, the answer, the kind, the Word
(`{ref, text}`) when the Gate was open, and the seal cite when there was one. The Palace stores no
verifier and computes no verdict — it is the experience the witness *keeps*, app-side, in a local
JSONL (`NH_PALACE`, default `run/palace.jsonl`). The verification truth stays in the core.

## Use

```python
from nh_org.palace import Palace
from nh_org import console

p = Palace()                                   # reads run/palace.jsonl (or $NH_PALACE)
console.dispatch("what does scripture say about honest work",
                 gate_open=True, keep=True, palace=p)   # files the exchange at a locus
p.recall("honest labor")                       # walk to the fitting loci, best first
p.walk("comfort")                              # everything kept in the comfort room, in order
p.shape()                                      # {"rooms": N, "max_positions": M, "kept": K}
```
