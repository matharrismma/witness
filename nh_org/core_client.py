"""nh_org.core_client — the ONE link from the .org app to the Narrow Highway core.

V3 boundary (2026-10-20). The .org app NEVER imports `concordance`. Every verification and
every seal goes through the core engine's public HTTP door, `POST /verify`:

  * structured  {"steps": [ {id, domain, spec} ... ]}  → a trail of CONFIRMED / MISMATCH / ...
  * free text   {"claim": "<plain sentence>"}          → found + verified across the engine's domains
  * ?seal=0 (default here) is read-only; ?seal=1 mints the permanent, re-checkable receipt whose
    cite_url points at narrowhighway.org/s/<hash> (the RECORD lives on .org).

One engine, one corpus, two surfaces: the .org app holds no verifier and no corpus of its own.
Transport is a seam so tests can replay recorded core responses offline; the default speaks real HTTP.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

DEFAULT_CORE = "https://api.narrowhighway.com"

# The core doors the .org app is allowed to call. Each is a verification/retrieval primitive the
# engine already exposes; the app COMPOSES them (e.g. the Console) but reimplements none. Adding a
# door here is a reviewed decision (tests/test_boundary.py pins the set); a direct `import concordance`
# is never allowed. Read-only doors (GET) carry no side effect; /verify?seal=1 is the only write.
CORE_DOORS = ("/verify", "/ask", "/search", "/read", "/resolve", "/word_study", "/speak",
              "/seal", "/seals", "/badges")


def request_key(path: str, body: Dict[str, Any], query: str = "") -> str:
    """A stable key for (path, body, query) so a recorder and a replayer agree byte-for-byte."""
    blob = f"{path}?{query}\n" + json.dumps(body, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class CoreUnavailable(RuntimeError):
    """The core could not be reached. The .org app must degrade honestly, never fabricate a verdict."""


class HttpTransport:
    """The real door: one POST to the core over HTTP. stdlib only — no third-party client."""

    def __init__(self, base_url: Optional[str] = None, timeout: float = 30.0, retries: int = 5):
        self.base = (base_url or os.environ.get("NH_CORE_URL") or DEFAULT_CORE).rstrip("/")
        self.timeout = timeout
        self.retries = retries

    def post(self, path: str, body: Dict[str, Any], query: str = "") -> Dict[str, Any]:
        url = f"{self.base}{path}" + (f"?{query}" if query else "")
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, headers={"content-type": "application/json"}, method="POST")
        last = None
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                last = e
                # The core rate-limits /verify. Back off and retry rather than fabricate a verdict.
                if e.code in (429, 503) and attempt < self.retries:
                    wait = float(e.headers.get("Retry-After") or 0) or (2 ** attempt)
                    time.sleep(min(wait, 30.0))
                    continue
                raise CoreUnavailable(f"{url}: {e}") from e
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last = e
                if attempt < self.retries:
                    time.sleep(2 ** attempt)
                    continue
                raise CoreUnavailable(f"{url}: {e}") from e
        raise CoreUnavailable(f"{url}: {last}")

    def get(self, path: str, query: str = "") -> Dict[str, Any]:
        """GET a read-only core door (the record: /seal, /seals, …). Same backoff as post."""
        url = f"{self.base}{path}" + (f"?{query}" if query else "")
        req = urllib.request.Request(url, method="GET")
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code in (429, 503) and attempt < self.retries:
                    time.sleep(min(float(e.headers.get("Retry-After") or 0) or (2 ** attempt), 30.0))
                    continue
                raise CoreUnavailable(f"{url}: {e}") from e
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                if attempt < self.retries:
                    time.sleep(2 ** attempt)
                    continue
                raise CoreUnavailable(f"{url}: {e}") from e
        raise CoreUnavailable(url)

    def post_raw(self, path: str, body: Dict[str, Any], query: str = ""):
        """POST expecting a raw (possibly binary) response. Returns (status, bytes, content_type).
        Used by the voice door (/speak returns audio/mpeg, or 503 when the ceiling is unavailable —
        that 503 is the engine's documented FLOOR, returned here as status 503, not raised)."""
        url = f"{self.base}{path}" + (f"?{query}" if query else "")
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, headers={"content-type": "application/json"}, method="POST")
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return resp.status, resp.read(), resp.headers.get("content-type", "")
            except urllib.error.HTTPError as e:
                if e.code == 503:
                    return 503, b"", e.headers.get("content-type", "")  # the floor, not a failure
                if e.code == 429 and attempt < self.retries:
                    time.sleep(min(float(e.headers.get("Retry-After") or 0) or (2 ** attempt), 30.0))
                    continue
                raise CoreUnavailable(f"{url}: {e}") from e
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                if attempt < self.retries:
                    time.sleep(2 ** attempt)
                    continue
                raise CoreUnavailable(f"{url}: {e}") from e
        raise CoreUnavailable(url)


class RecordedTransport:
    """Replays a {request_key: response} map captured from the live core. Offline + deterministic.

    A missing key is an error, not a silent empty verdict: the fixture must cover every call the
    test makes, or the test is lying about what the core said."""

    def __init__(self, recording: Dict[str, Any]):
        self.recording = recording
        self.seen: List[str] = []

    def post(self, path: str, body: Dict[str, Any], query: str = "") -> Dict[str, Any]:
        return self._replay(path, body, query)

    def get(self, path: str, query: str = "") -> Dict[str, Any]:
        return self._replay(path, {}, query)

    def _replay(self, path: str, body: Dict[str, Any], query: str = "") -> Dict[str, Any]:
        k = request_key(path, body, query)
        self.seen.append(k)
        if k not in self.recording:
            raise CoreUnavailable(
                f"no recorded core response for {path}?{query} (key {k[:12]}…); re-record the fixture")
        return self.recording[k]


class RecordingTransport:
    """Wraps a real transport and captures every (key -> response) for later offline replay."""

    def __init__(self, inner: Optional[HttpTransport] = None, delay: float = 0.25):
        self.inner = inner or HttpTransport()
        self.recording: Dict[str, Any] = {}
        self.delay = delay  # be polite to the core's rate limiter while recording a whole batch

    def post(self, path: str, body: Dict[str, Any], query: str = "") -> Dict[str, Any]:
        out = self.inner.post(path, body, query)
        self.recording[request_key(path, body, query)] = out
        if self.delay:
            time.sleep(self.delay)
        return out

    def get(self, path: str, query: str = "") -> Dict[str, Any]:
        out = self.inner.get(path, query)
        self.recording[request_key(path, {}, query)] = out
        if self.delay:
            time.sleep(self.delay)
        return out


class CoreClient:
    """The engine, as the .org app sees it: verify (read-only) and seal (opt-in, a write)."""

    def __init__(self, transport: Optional[Any] = None):
        self.t = transport or HttpTransport()

    def verify(self, steps: List[Dict[str, Any]], *, seal: bool = False) -> Dict[str, Any]:
        """Run a structured derivation through the core. Returns {verdict, trail:[...], house:{...}}."""
        return self.t.post("/verify", {"steps": steps}, "seal=1" if seal else "seal=0")

    def verify_text(self, claim: str, *, seal: bool = False) -> Dict[str, Any]:
        """Hand the core a plain-language claim; it finds + verifies the checkable parts."""
        return self.t.post("/verify", {"claim": claim}, "seal=1" if seal else "seal=0")

    def ask(self, text: str, *, thread_id: Optional[str] = None,
            gate_open: bool = False) -> Dict[str, Any]:
        """The WALK door: a situation or question in, one next step out. The engine finds + verifies
        + cites, never generates. Returns {kind, message, verify, house:{next_step}, gate_open, ...},
        and when the Gate is open also the Word (`path.anchor`), the shepherd step (`path`) and the
        public-domain witness `cloud`. `gate_open` follows the surface: the .org/witness face opens
        it, the .com/secular face leaves it closed (Ask/Seek/Knock — the person's seeking opens it).
        This is the primitive the Console composes."""
        body: Dict[str, Any] = {"text": text}
        if thread_id:
            body["thread_id"] = thread_id
        if gate_open:
            body["gate_open"] = True
        return self.t.post("/ask", body)

    def speak(self, text: str) -> Dict[str, Any]:
        """The voice ceiling: ask the core to speak `text` (audio/mpeg). Returns
        {spoken, floor, mime, audio}. When the ceiling is unavailable (no ElevenLabs credits) the
        core returns its 503 FLOOR and this reports spoken=False, floor=True with no audio — the
        caller then falls back to the browser floor (NHSpeak) or plain text. Never fabricates audio.
        A transport without raw support (e.g. a recorded JSON transport) also yields the floor."""
        raw = getattr(self.t, "post_raw", None)
        if raw is None:
            return {"spoken": False, "floor": True, "mime": None, "audio": None}
        status, audio, mime = raw("/speak", {"text": text})
        if status == 200 and audio:
            return {"spoken": True, "floor": False, "mime": mime or "audio/mpeg", "audio": audio}
        return {"spoken": False, "floor": True, "mime": None, "audio": None}

    def seal(self, content_hash: str) -> Optional[Dict[str, Any]]:
        """Fetch a sealed record (the receipt) by its content hash — re-check the testimony. The
        record lives on .org; this is how the witness app reads it. Returns None if not found."""
        import urllib.parse
        try:
            return self.t.get("/seal", "hash=" + urllib.parse.quote(content_hash))
        except CoreUnavailable as e:
            if "404" in str(e):
                return None
            raise

    def seals(self, *, limit: int = 20) -> Dict[str, Any]:
        """The ledger of sealed records — {note, seals:[...]}."""
        return self.t.get("/seals", f"limit={int(limit)}")

    def badge(self, seal_hashes: List[str], *, title: str = "",
              subject_id: Optional[str] = None) -> Dict[str, Any]:
        """Compose sealed checks into a badge — the EVIDENCE, issued UNSIGNED (the core's contract:
        'the evidence, not the signature, is the badge'). Binding it to an identity is a separate,
        signed step the holder does on their own device; this app does not sign on their behalf."""
        body: Dict[str, Any] = {"seal_hashes": list(seal_hashes), "title": title}
        if subject_id:
            body["subject_id"] = subject_id
        return self.t.post("/badges", body)

    @staticmethod
    def seal_of(result: Dict[str, Any]) -> Dict[str, Any]:
        """The receipt a verify returned, wherever the core placed it (top level or in `house`)."""
        return result.get("seal") or (result.get("house") or {}).get("seal") or {}
