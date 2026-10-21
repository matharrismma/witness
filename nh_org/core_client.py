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
CORE_DOORS = ("/verify", "/ask", "/search", "/read", "/resolve", "/word_study")


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


class RecordedTransport:
    """Replays a {request_key: response} map captured from the live core. Offline + deterministic.

    A missing key is an error, not a silent empty verdict: the fixture must cover every call the
    test makes, or the test is lying about what the core said."""

    def __init__(self, recording: Dict[str, Any]):
        self.recording = recording
        self.seen: List[str] = []

    def post(self, path: str, body: Dict[str, Any], query: str = "") -> Dict[str, Any]:
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

    def ask(self, text: str, *, thread_id: Optional[str] = None) -> Dict[str, Any]:
        """The WALK door: a situation or question in, one next step out. The engine finds + verifies
        + cites, never generates. Returns {kind, message, verify, house:{next_step}, gate_open, ...}.
        This is the primitive the Console composes — the Console's experience lives in the app, the
        finding and the verdict live in the core."""
        body: Dict[str, Any] = {"text": text}
        if thread_id:
            body["thread_id"] = thread_id
        return self.t.post("/ask", body)

    @staticmethod
    def seal_of(result: Dict[str, Any]) -> Dict[str, Any]:
        """The receipt a verify returned, wherever the core placed it (top level or in `house`)."""
        return result.get("seal") or (result.get("house") or {}).get("seal") or {}
