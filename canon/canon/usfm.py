"""usfm — read the World English Bible (public domain, ebible.org USFM with inline Strong's tags) into
verse rows. Nothing is generated: every row is the verbatim verse text, plus the Strong's numbers the
tagging carries, so a word study can find the same verses the text does.

    rows = list(read_dir("eng-web_usfm/"))     # {"book","chapter","verse","text","strongs":[...]}
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Iterator, List

# USFM 3-letter ids → canonical English names and the openbible.info abbreviations used by cross_references.txt
BOOKS: Dict[str, tuple] = {
    "GEN": ("Genesis", "Gen"), "EXO": ("Exodus", "Exod"), "LEV": ("Leviticus", "Lev"), "NUM": ("Numbers", "Num"),
    "DEU": ("Deuteronomy", "Deut"), "JOS": ("Joshua", "Josh"), "JDG": ("Judges", "Judg"), "RUT": ("Ruth", "Ruth"),
    "1SA": ("1 Samuel", "1Sam"), "2SA": ("2 Samuel", "2Sam"), "1KI": ("1 Kings", "1Kgs"), "2KI": ("2 Kings", "2Kgs"),
    "1CH": ("1 Chronicles", "1Chr"), "2CH": ("2 Chronicles", "2Chr"), "EZR": ("Ezra", "Ezra"), "NEH": ("Nehemiah", "Neh"),
    "EST": ("Esther", "Esth"), "JOB": ("Job", "Job"), "PSA": ("Psalms", "Ps"), "PRO": ("Proverbs", "Prov"),
    "ECC": ("Ecclesiastes", "Eccl"), "SNG": ("Song of Solomon", "Song"), "ISA": ("Isaiah", "Isa"), "JER": ("Jeremiah", "Jer"),
    "LAM": ("Lamentations", "Lam"), "EZK": ("Ezekiel", "Ezek"), "DAN": ("Daniel", "Dan"), "HOS": ("Hosea", "Hos"),
    "JOL": ("Joel", "Joel"), "AMO": ("Amos", "Amos"), "OBA": ("Obadiah", "Obad"), "JON": ("Jonah", "Jonah"),
    "MIC": ("Micah", "Mic"), "NAM": ("Nahum", "Nah"), "HAB": ("Habakkuk", "Hab"), "ZEP": ("Zephaniah", "Zeph"),
    "HAG": ("Haggai", "Hag"), "ZEC": ("Zechariah", "Zech"), "MAL": ("Malachi", "Mal"),
    "MAT": ("Matthew", "Matt"), "MRK": ("Mark", "Mark"), "LUK": ("Luke", "Luke"), "JHN": ("John", "John"),
    "ACT": ("Acts", "Acts"), "ROM": ("Romans", "Rom"), "1CO": ("1 Corinthians", "1Cor"), "2CO": ("2 Corinthians", "2Cor"),
    "GAL": ("Galatians", "Gal"), "EPH": ("Ephesians", "Eph"), "PHP": ("Philippians", "Phil"), "COL": ("Colossians", "Col"),
    "1TH": ("1 Thessalonians", "1Thess"), "2TH": ("2 Thessalonians", "2Thess"), "1TI": ("1 Timothy", "1Tim"),
    "2TI": ("2 Timothy", "2Tim"), "TIT": ("Titus", "Titus"), "PHM": ("Philemon", "Phlm"), "HEB": ("Hebrews", "Heb"),
    "JAS": ("James", "Jas"), "1PE": ("1 Peter", "1Pet"), "2PE": ("2 Peter", "2Pet"), "1JN": ("1 John", "1John"),
    "2JN": ("2 John", "2John"), "3JN": ("3 John", "3John"), "JUD": ("Jude", "Jude"), "REV": ("Revelation", "Rev"),
}
ABBR_TO_NAME = {abbr: name for name, abbr in BOOKS.values()}
NAME_TO_ABBR = {name: abbr for name, abbr in BOOKS.values()}

_W = re.compile(r'\\\+?w ([^|\\]+?)\|strong="([^"]+)"\\\+?w\*')      # \w word|strong="H1234"\w*  (and nested \+w)
_W_PLAIN = re.compile(r"\\\+?w ([^|\\]+?)\\\+?w\*")
_NOTE = re.compile(r"\\(f|x|fe)\s.*?\\\1\*", re.S)              # footnotes and cross-ref notes
_INLINE = re.compile(r"\\\+?(wj|nd|add|qs|bk|tl|sc|it|bd|em|k|qt)\s?([^\\]*?)\\\+?\1\*")   # keep the inner text
_MARK = re.compile(r"\\[a-z0-9]+\*?\s?")                        # any remaining marker
_SPACE = re.compile(r"\s+")


def _clean(raw: str) -> tuple:
    strongs: List[str] = []
    raw = _NOTE.sub("", raw)
    for m in _W.finditer(raw):
        strongs.extend(s for s in m.group(2).replace(",", " ").split() if s)
    raw = _W.sub(r"\1", raw)
    raw = _W_PLAIN.sub(r"\1", raw)
    for _ in range(3):
        raw = _INLINE.sub(r"\2", raw)
    raw = _MARK.sub(" ", raw)
    text = _SPACE.sub(" ", raw).strip()
    text = re.sub(r"\s+([,.;:!?’”)])", r"\1", text)
    return text, strongs


def read_file(path: Path) -> Iterator[Dict]:
    book = None
    chapter = 0
    verse = None
    buf: List[str] = []

    def flush():
        nonlocal buf
        if book and verse is not None and buf:
            text, strongs = _clean(" ".join(buf))
            if text:
                yield {"book": BOOKS[book][0], "abbr": BOOKS[book][1], "chapter": chapter, "verse": verse,
                       "text": text, "strongs": strongs}
        buf = []

    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("\\id "):
            code = line.split()[1]
            if code not in BOOKS:
                return
            book = code
            continue
        if line.startswith("\\c "):
            yield from flush()
            chapter = int(line.split()[1])
            verse = None
            continue
        # a line may carry several \v markers
        parts = re.split(r"(\\v \d+[a-z]?\s)", line)
        for part in parts:
            m = re.match(r"\\v (\d+)[a-z]?\s", part)
            if m:
                yield from flush()
                verse = int(m.group(1))
            elif verse is not None:
                if part.startswith("\\s") or part.startswith("\\r") or part.startswith("\\d"):
                    continue    # section heads and descriptive titles are not verse text
                buf.append(part)
    yield from flush()


def read_dir(d: Path) -> Iterator[Dict]:
    for p in sorted(Path(d).glob("*.usfm")):
        yield from read_file(p)


__all__ = ["read_file", "read_dir", "BOOKS", "ABBR_TO_NAME", "NAME_TO_ABBR"]
