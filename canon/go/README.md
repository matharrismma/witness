# canon (Go)

The same hash table as `canon/table.py`, as one static binary for the edge: no Python, no CGO, ~6 MB.

```bash
cd go && CGO_ENABLED=0 go build -ldflags="-s -w" -o canon .
./canon -data ../data -check            # recomputes every verse key and the root; refuses to start on any mismatch
./canon -data ../data -addr :8040        # POST /tool/{read_passage|find_text|cross_refs|word_study}, POST /verify, GET /manifest
```

Measured 2026-10-28: root identical to the Python table (`dd645c66…`, 31,098 verses); 606 tool calls
cross-checked against `canon/synth.py` with 0 differing answers; `find_text` ≈ 8 ms per call on one core.
The Go side reads what the Python side built; the key check at startup is what makes them one commitment.
