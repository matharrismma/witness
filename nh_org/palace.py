"""The Palace — the Console's "keep", built as a memory palace (method of loci).

Matt (2026-10-21): "sorting algorithms, tensors and memory palaces can assist." They do, here:

- **Memory palace** — every kept exchange is placed at a LOCUS `(room, position)` you can walk back
  to. The room is the exchange's kind/theme; the position is its order within that room. Recall is a
  walk, not a scan.
- **Tensor** — the loci form a 2-axis grid, `room × position`. `shape()` reports that tensor's
  extent; a room is one axis fixed, walked along the other.
- **Sorting** — `recall(cue)` ranks every kept locus by relevance (token overlap, normalized) with
  recency as the tiebreak, and returns the top of that sort. The ranking is explicit and stable.

The Palace holds only what the core already found/verified (each item carries the Word and the seal
cite when there was one); it stores no verifier and computes no verdict. It is app-side state —
the experience the witness keeps — written to a local JSONL the operator points at.
"""
from __future__ import annotations

import json
import math
import os
import re
import time
from collections import Counter
from typing import Any, Dict, List, Optional

_WORD = re.compile(r"[a-z]{3,}")


def _toks(s: Optional[str]) -> set:
    return set(_WORD.findall((s or "").lower()))


class Palace:
    def __init__(self, path: Optional[str] = None):
        self.path = path or os.environ.get("NH_PALACE") or os.path.join("run", "palace.jsonl")
        self.items: List[Dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as f:
                self.items = [json.loads(ln) for ln in f if ln.strip()]
        except FileNotFoundError:
            self.items = []

    def _room_of(self, kind: Optional[str], theme: Optional[str], text: str) -> str:
        if kind:
            return str(kind)
        strongest = sorted(_toks(theme) or _toks(text))
        return strongest[0] if strongest else "hall"

    def keep(self, *, text: str, answer: Optional[str], kind: Optional[str] = None,
             word: Optional[Dict[str, Any]] = None, cite: Optional[str] = None,
             theme: Optional[str] = None, now: Optional[float] = None) -> Dict[str, Any]:
        """Place one exchange in the palace at its locus and persist it."""
        room = self._room_of(kind, theme, text)
        position = sum(1 for it in self.items if it["locus"]["room"] == room)
        rec = {
            "id": f"{room}:{position}:{int((now or time.time()) * 1000)}",
            "kept_at": now if now is not None else time.time(),
            "text": text, "answer": answer, "kind": kind,
            "word": word, "cite": cite, "theme": theme or text,
            "locus": {"room": room, "position": position},
        }
        self.items.append(rec)
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return rec

    def recall(self, cue: str, k: int = 5) -> List[Dict[str, Any]]:
        """Walk the palace to the loci that fit the cue, best first (the sort)."""
        ct = _toks(cue)
        scored = []
        for it in self.items:
            text = _toks(it.get("theme")) | _toks(it.get("text")) | _toks(it.get("answer"))
            overlap = len(ct & text)
            if not overlap:
                continue
            score = overlap / math.sqrt(max(1, len(text)))  # normalize so a long record cannot dominate
            scored.append((score, it.get("kept_at", 0.0), it))
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)  # relevance, then recency
        return [dict(it, score=round(s, 4)) for s, _, it in scored[:k]]

    def walk(self, room: str, k: Optional[int] = None) -> List[Dict[str, Any]]:
        """Everything kept in one room, in the order it was placed (the loci along the position axis)."""
        inroom = sorted((it for it in self.items if it["locus"]["room"] == room),
                        key=lambda it: it["locus"]["position"])
        return inroom[:k] if k else inroom

    def rooms(self) -> Dict[str, int]:
        return dict(Counter(it["locus"]["room"] for it in self.items))

    def shape(self) -> Dict[str, int]:
        """The tensor's extent: how many rooms, the deepest room, how many loci in all."""
        r = self.rooms()
        return {"rooms": len(r), "max_positions": max(r.values()) if r else 0, "kept": len(self.items)}
