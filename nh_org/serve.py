"""The witness web server — serves narrowhighway.org by composing the core.

A small stdlib HTTP server (no framework). It renders the Console as a STILL page and exposes the
read surfaces as JSON. Every answer is the core's — found, verified, cited — never generated here.
The routing is a pure function, `handle(...)`, so it is tested without sockets; `main()` binds it to
an HTTPServer for deployment. The .org face opens the Gate by default (the Word is woven in).

  GET  /                      the landing page (an ask box → /book)
  GET  /book?q=<ask>          the answer as a still E-Ink page (server-rendered)
  GET  /health                {ok, surface, doors}
  POST /console  {text}       the Console payload as JSON (for agents)
  GET  /mesh | /groups | /teachings | /decks     a read surface, as JSON
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional, Tuple

from . import community, study
from .console import book, dispatch
from .core_client import CORE_DOORS, CoreClient, CoreUnavailable

_LANDING = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Narrow Highway</title><style>
:root{--bg:#f7f6f1;--ink:#17150f;--soft:#5c574a;--accent:#6b4f1d}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#14130f;--ink:#ece7d9;--soft:#a39a84;--accent:#c9a34b;color-scheme:dark}}
html,body{margin:0;background:var(--bg);color:var(--ink)}
body{font:18px/1.6 Georgia,serif;padding:0 16px;min-height:100%}
main{max-width:34rem;margin:0 auto;padding:4rem 0}
h1{font-weight:600;letter-spacing:.01em}
p{color:var(--soft)}
form{margin-top:2rem;display:flex;gap:.5rem;flex-wrap:wrap}
input[name=q]{flex:1;min-width:0;font:inherit;padding:.6rem .8rem;border:1px solid var(--accent);border-radius:.3rem;background:transparent;color:var(--ink)}
button{font:inherit;padding:.6rem 1rem;border:1px solid var(--accent);border-radius:.3rem;background:var(--accent);color:var(--bg);cursor:pointer}
</style></head><body><main>
<h1>Narrow Highway</h1>
<p>Bring a word, a question, a claim, a verse. What comes back is found and verified, never generated.</p>
<form action="/book" method="get"><input name="q" placeholder="what do you bring?" autofocus>
<button>Ask</button></form>
</main></body></html>
"""


def _json(status: int, obj: Any) -> Tuple[int, str, bytes]:
    return status, "application/json; charset=utf-8", json.dumps(obj).encode("utf-8")


def _page(status: int, h: str) -> Tuple[int, str, bytes]:
    return status, "text/html; charset=utf-8", h.encode("utf-8")


def _query(query: str) -> Dict[str, str]:
    import urllib.parse
    return {k: v[0] for k, v in urllib.parse.parse_qs(query).items()}


def handle(method: str, path: str, query: str = "", body: Optional[Dict[str, Any]] = None, *,
           client: Optional[CoreClient] = None, gate_open: bool = True) -> Tuple[int, str, bytes]:
    """Route one request. Pure: returns (status, content_type, body_bytes). Never raises on a core
    outage — it answers with an honest 503, never a fabricated page."""
    client = client or CoreClient()
    q = _query(query)
    try:
        if method == "GET" and path in ("/", "/index.html"):
            return _page(200, _LANDING)
        if method == "GET" and path == "/health":
            return _json(200, {"ok": True, "surface": "witness", "doors": list(CORE_DOORS)})
        if method == "GET" and path == "/book":
            ask = (q.get("q") or "").strip()
            if not ask:
                return _page(200, _LANDING)
            out = dispatch(ask, client=client, gate_open=gate_open)
            return _page(200, book.render(out, title="The Console"))
        if method == "POST" and path == "/console":
            text = str((body or {}).get("text") or "").strip()
            if not text:
                return _json(400, {"error": "text required"})
            return _json(200, dispatch(text, client=client, gate_open=gate_open))
        if method == "GET" and path == "/mesh":
            return _json(200, community.overview(client=client))
        if method == "GET" and path == "/groups":
            return _json(200, community.groups(client=client))
        if method == "GET" and path == "/teachings":
            return _json(200, study.teachings(client=client))
        if method == "GET" and path == "/decks":
            return _json(200, study.decks(client=client))
        return _json(404, {"error": "no such door", "try": ["/", "/book?q=", "/console", "/health"]})
    except CoreUnavailable as e:
        return _json(503, {"error": "the core is unavailable; nothing was fabricated", "detail": str(e)})


def main() -> int:
    import os
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    host = os.environ.get("NH_ORG_HOST", "127.0.0.1")
    port = int(os.environ.get("NH_ORG_PORT", "8010"))
    gate = os.environ.get("NH_ORG_GATE", "1") not in ("0", "false", "no")

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _serve(self, method: str):
            from urllib.parse import urlsplit
            u = urlsplit(self.path)
            body = None
            if method == "POST":
                n = int(self.headers.get("content-length") or 0)
                raw = self.rfile.read(n) if n else b""
                try:
                    body = json.loads(raw or b"{}")
                except (ValueError, TypeError):
                    body = {}
            status, ctype, data = handle(method, u.path, u.query, body, gate_open=gate)
            self.send_response(status)
            self.send_header("content-type", ctype)
            self.send_header("content-length", str(len(data)))
            self.send_header("x-content-type-options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self._serve("GET")

        def do_POST(self):
            self._serve("POST")

        def log_message(self, *a):  # quiet by default
            pass

    srv = ThreadingHTTPServer((host, port), Handler)
    print(f"witness serving on http://{host}:{port} (gate_open={gate}) → core {CoreClient().t.base}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
