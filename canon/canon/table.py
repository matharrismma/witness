"""table — the canon as a hash table: every verse is a bucket.

    key = sha256(canonical({"translation", "book", "chapter", "verse", "text"}))

The text never lives in a model's weights here; it lives in this table, where it cannot drift. A quote
is checked by normalising it the same way the table was built and looking it up: a hit is HOLDS, a miss
is a counterexample with the nearest verse named. No tolerance — this is the pure stratum. Cross-references
(openbible.info, CC-BY) are a second table keyed by reference.

    t = Table.load(data_dir)             # data/canon/web.jsonl + xrefs.tsv
    t.get("John", 3, 16)                 # the row, or None
    t.find_text("For God so loved…")     # exact-after-normalisation lookup → row | None
    t.nearest("For God so loved the wrld")  # (row, distance) — the counterexample's neighbour
    t.xrefs("John", 3, 16)               # [("Rom", 5, 8, votes), ...]
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .usfm import ABBR_TO_NAME, NAME_TO_ABBR

TRANSLATION = "WEB"
_PUNCT = re.compile(r"[^\w\s]")
_SPACE = re.compile(r"\s+")


def canonical_bytes(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8", "surrogatepass")


def normalise(text: str) -> str:
    """One normal form for lookup: NFKC, straight quotes, lower, punctuation dropped, single spaces. Two
    renderings of the same verse hash the same; a changed word does not."""
    t = unicodedata.normalize("NFKC", text or "")
    t = t.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').replace("—", " ").replace("–", " ")
    t = _PUNCT.sub(" ", t.lower())
    return _SPACE.sub(" ", t).strip()


def verse_key(book: str, chapter: int, verse: int, text: str, translation: str = TRANSLATION) -> str:
    return hashlib.sha256(canonical_bytes({"translation": translation, "book": book, "chapter": int(chapter),
                                           "verse": int(verse), "text": normalise(text)})).hexdigest()


def text_key(text: str, translation: str = TRANSLATION) -> str:
    """Keyed on the text alone — how a quote with no reference is looked up."""
    return hashlib.sha256(canonical_bytes({"translation": translation, "text": normalise(text)})).hexdigest()


def parse_ref(ref: str) -> Optional[Tuple[str, int, int]]:
    """'John 3:16', 'John.3.16', 'Jn 3:16' (abbr), '1 Cor 13:4' → ('1 Corinthians', 13, 4)."""
    s = (ref or "").strip().replace(".", " ").replace(":", " ")
    m = re.match(r"^((?:[1-3]\s?)?[A-Za-z]+(?:\s+of\s+[A-Za-z]+)?)\s+(\d+)\s+(\d+)[a-z]?$", s)
    if not m:
        return None
    book_raw = re.sub(r"\s+", " ", m.group(1)).strip()
    book = _resolve_book(book_raw)
    return (book, int(m.group(2)), int(m.group(3))) if book else None


_ALIASES = {"psalm": "Psalms", "song of songs": "Song of Solomon", "canticles": "Song of Solomon",
            "revelations": "Revelation", "jn": "John", "jhn": "John", "mt": "Matthew", "mk": "Mark", "lk": "Luke",
            "rev": "Revelation", "gen": "Genesis", "ex": "Exodus", "dt": "Deuteronomy", "ps": "Psalms", "prov": "Proverbs",
            "isa": "Isaiah", "rom": "Romans", "heb": "Hebrews", "eph": "Ephesians", "phil": "Philippians", "col": "Colossians"}


def _resolve_book(raw: str) -> Optional[str]:
    key = raw.lower().replace(" ", "")
    for name in NAME_TO_ABBR:
        if name.lower().replace(" ", "") == key:
            return name
    for abbr, name in ABBR_TO_NAME.items():
        if abbr.lower() == key:
            return name
    low = raw.lower()
    if low in _ALIASES:
        return _ALIASES[low]
    for name in NAME_TO_ABBR:
        if name.lower().replace(" ", "").startswith(key) and len(key) >= 3:
            return name
    return None


class Table:
    def __init__(self, rows: Iterable[Dict[str, Any]], xrefs: Optional[Iterable[Tuple[str, str, int]]] = None,
                 translation: str = TRANSLATION):
        self.translation = translation
        self.rows: List[Dict[str, Any]] = []
        self.by_ref: Dict[Tuple[str, int, int], Dict[str, Any]] = {}
        self.by_text: Dict[str, Dict[str, Any]] = {}
        self.by_key: Dict[str, Dict[str, Any]] = {}
        self.by_strong: Dict[str, List[Tuple[str, int, int]]] = defaultdict(list)
        self.by_word: Dict[str, List[int]] = defaultdict(list)       # inverted index → row positions
        self._norm: List[str] = []
        for r in rows:
            r = dict(r)
            r["key"] = verse_key(r["book"], r["chapter"], r["verse"], r["text"], translation)
            self.rows.append(r)
            self.by_ref[(r["book"], int(r["chapter"]), int(r["verse"]))] = r
            self.by_text[text_key(r["text"], translation)] = r
            self.by_key[r["key"]] = r
            for s in r.get("strongs") or []:
                self.by_strong[s].append((r["book"], int(r["chapter"]), int(r["verse"])))
            n = normalise(r["text"])
            self._norm.append(n)
            for w in set(n.split()):
                self.by_word[w].append(len(self.rows) - 1)
        self._xrefs: Dict[Tuple[str, int, int], List[Tuple[str, int, int, int]]] = defaultdict(list)
        for src, dst, votes in (xrefs or []):
            a, b = _parse_ob(src), _parse_ob(dst)
            if a and b:
                self._xrefs[a].append((*b, int(votes)))
        for k in self._xrefs:
            self._xrefs[k].sort(key=lambda x: -x[3])

    # ── lookups: the hash table ───────────────────────────────────────────────────────────────────
    def get(self, book: str, chapter: int, verse: int) -> Optional[Dict[str, Any]]:
        return self.by_ref.get((book, int(chapter), int(verse)))

    def find_text(self, text: str) -> Optional[Dict[str, Any]]:
        return self.by_text.get(text_key(text, self.translation))

    def find_phrase(self, phrase: str) -> List[Dict[str, Any]]:
        """Verses containing the phrase verbatim (after normalisation). Candidates come from the rarest word."""
        q = normalise(phrase)
        words = q.split()
        if not words:
            return []
        rare = min(words, key=lambda w: len(self.by_word.get(w, ())))
        return [self.rows[i] for i in self.by_word.get(rare, []) if f" {q} " in f" {self._norm[i]} "]

    def verses_in(self, text: str, min_words: int = 6) -> List[Dict[str, Any]]:
        """Verses (≥ min_words long) that appear verbatim INSIDE the text — how uncited scripture is caught."""
        n = f" {normalise(text)} "
        words = n.split()
        if len(words) < min_words:
            return []
        seen: Dict[int, None] = {}
        for w in sorted(set(words), key=lambda w: len(self.by_word.get(w, ())))[:12]:
            for i in self.by_word.get(w, []):
                seen.setdefault(i, None)
        return [self.rows[i] for i in seen if len(self._norm[i].split()) >= min_words and f" {self._norm[i]} " in n]

    def xrefs(self, book: str, chapter: int, verse: int, limit: int = 10) -> List[Tuple[str, int, int, int]]:
        return self._xrefs.get((book, int(chapter), int(verse)), [])[:limit]

    def with_strong(self, strong: str, limit: int = 20) -> List[Tuple[str, int, int]]:
        return self.by_strong.get(strong, [])[:limit]

    # ── the neighbour of a miss: where a counterexample points ───────────────────────────────────
    def nearest(self, text: str, within: Optional[Tuple[str, int, int]] = None, window: int = 3) -> Tuple[Optional[Dict[str, Any]], int]:
        """The closest verse by token edit distance. With `within`, only verses near that reference are
        searched (the claimed reference is the first suspect); otherwise a word-overlap prefilter picks
        candidates across the whole canon."""
        q = normalise(text).split()
        if not q:
            return None, 0
        cands: List[Dict[str, Any]] = []
        if within:
            b, c, v = within
            for dv in range(-window, window + 1):
                r = self.by_ref.get((b, c, v + dv))
                if r:
                    cands.append(r)
        if not cands:
            # candidates: verses sharing the query's rarest words (inverted index), scored by overlap
            qs = set(q)
            counts: Dict[int, int] = defaultdict(int)
            for w in sorted(qs, key=lambda w: len(self.by_word.get(w, ())))[:8]:
                for i in self.by_word.get(w, []):
                    counts[i] += 1
            scored = sorted(counts.items(), key=lambda kv: -kv[1])[:60]
            cands = [self.rows[i] for i, _ in scored]
        best, bd = None, 10 ** 9
        for r in cands:
            d = _edit(q, normalise(r["text"]).split())
            if d < bd:
                best, bd = r, d
        return best, bd

    # ── persistence ───────────────────────────────────────────────────────────────────────────────
    def save(self, data_dir: Path) -> Dict[str, Any]:
        d = Path(data_dir)
        d.mkdir(parents=True, exist_ok=True)
        with open(d / "web.jsonl", "w", encoding="utf-8") as f:
            for r in self.rows:
                f.write(json.dumps({k: r[k] for k in ("book", "abbr", "chapter", "verse", "text", "strongs", "key")},
                                   ensure_ascii=False) + "\n")
        with open(d / "xrefs.tsv", "w", encoding="utf-8") as f:
            for (b, c, v), lst in self._xrefs.items():
                for tb, tc, tv, votes in lst:
                    f.write(f"{NAME_TO_ABBR[b]}.{c}.{v}\t{NAME_TO_ABBR[tb]}.{tc}.{tv}\t{votes}\n")
        root = hashlib.sha256(b"".join(bytes.fromhex(r["key"]) for r in self.rows)).hexdigest()
        manifest = {"translation": self.translation, "verses": len(self.rows), "books": len({r["book"] for r in self.rows}),
                    "xref_sources": len(self._xrefs), "root": root,
                    "means": "root = sha256 of every verse key in canonical order; the whole canon is one commitment"}
        (d / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
        return manifest

    @classmethod
    def load(cls, data_dir: Path) -> "Table":
        d = Path(data_dir)
        rows = [json.loads(l) for l in open(d / "web.jsonl", encoding="utf-8") if l.strip()]
        xr = []
        p = d / "xrefs.tsv"
        if p.exists():
            for line in open(p, encoding="utf-8"):
                a, b, votes = line.rstrip("\n").split("\t")
                xr.append((a, b, int(votes)))
        return cls(rows, xr)

    @classmethod
    def build(cls, usfm_dir: Path, xrefs_txt: Optional[Path] = None) -> "Table":
        from .usfm import read_dir
        xr = []
        if xrefs_txt and Path(xrefs_txt).exists():
            for line in open(xrefs_txt, encoding="utf-8"):
                if line.startswith("From Verse") or not line.strip():
                    continue
                parts = line.rstrip("\n").split("\t")
                if len(parts) >= 3 and "-" not in parts[0] and "-" not in parts[1]:   # single verses only
                    xr.append((parts[0], parts[1], int(parts[2])))
        return cls(read_dir(usfm_dir), xr)


def _parse_ob(s: str) -> Optional[Tuple[str, int, int]]:
    """openbible.info form: Gen.1.1"""
    parts = s.split(".")
    if len(parts) != 3:
        return None
    name = ABBR_TO_NAME.get(parts[0])
    if not name:
        return None
    try:
        return (name, int(parts[1]), int(parts[2]))
    except ValueError:
        return None


def _edit(a: List[str], b: List[str]) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


__all__ = ["Table", "normalise", "verse_key", "text_key", "parse_ref", "TRANSLATION"]
