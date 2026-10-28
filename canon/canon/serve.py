"""serve — the four canon tools over HTTP, for a model (or a person) to call. Stdlib only.

    POST /tool/{read_passage|find_text|cross_refs|word_study}   JSON args in → JSON out (synth.run_tool)
    POST /verify   {"quote": ..., "ref": ...}  → the scripture verifier's results (no engine needed)
    GET  /manifest  the canon's root commitment
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .synth import run_tool
from .table import Table


def serve(t: Table, host: str = "127.0.0.1", port: int = 8040) -> None:
    manifest = json.loads((Path(__file__).resolve().parents[1] / "data" / "manifest.json").read_text())

    class H(BaseHTTPRequestHandler):
        def _json(self, code, obj):
            b = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

        def do_GET(self):
            if self.path == "/manifest":
                return self._json(200, manifest)
            return self._json(404, {"error": "not found"})

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except json.JSONDecodeError:
                return self._json(400, {"error": "bad json"})
            if self.path.startswith("/tool/"):
                return self._json(200, run_tool(t, self.path[6:], body))
            if self.path == "/verify":
                from . import verifier
                verifier._TABLE = t
                res = verifier.run({"SCRIPTURE_VERIFY": body})
                return self._json(200, [{"name": getattr(r, "name", None) or r.get("name"), "status": getattr(r, "status", None) or r.get("status"),
                                         "detail": getattr(r, "detail", None) or r.get("detail"), "data": getattr(r, "data", None) or r.get("data")} for r in res])
            return self._json(404, {"error": "not found"})

        def log_message(self, *a):  # quiet
            pass

    print(f"canon tools on http://{host}:{port}/  (root {manifest['root'][:12]}…, {manifest['verses']} verses)")
    ThreadingHTTPServer((host, port), H).serve_forever()
