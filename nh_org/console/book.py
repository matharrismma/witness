"""The BOOK — render a Console answer as a still, readable page (the counterpart to the RADIO voice).

E-Ink-first per the Console design: high-contrast serif, a single readable column, page-not-scroll,
reduced-motion, a STATIC one-frame trail (door → verifier(s) → seal → source) — no animation. Pure
presentation: it renders only what `console.dispatch` returned (the core's found/verified content),
escapes every interpolated value, loads nothing external, runs no script, generates no prose.
"""
from __future__ import annotations

import html
from typing import Any, Dict, List, Optional

_CSS = """
:root{--bg:#f7f6f1;--ink:#17150f;--soft:#5c574a;--line:#d9d4c6;--accent:#6b4f1d}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#14130f;--ink:#ece7d9;--soft:#a39a84;--line:#2e2a20;--accent:#c9a34b;color-scheme:dark}}
:root[data-theme=dark]{--bg:#14130f;--ink:#ece7d9;--soft:#a39a84;--line:#2e2a20;--accent:#c9a34b;color-scheme:dark}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--ink)}
body{font:18px/1.6 Georgia,"Iowan Old Style",'Times New Roman',serif;padding:0 16px}
main{max-width:38rem;margin:0 auto;padding:2.2rem 0 3rem}
h1{font-size:1.15rem;font-weight:600;letter-spacing:.02em;color:var(--soft);text-transform:uppercase;margin:0 0 1.4rem}
p{margin:0 0 1rem;text-wrap:pretty}
.word{border-left:3px solid var(--accent);padding:.1rem 0 .1rem 1rem;margin:1.6rem 0;color:var(--ink)}
.word .ref{display:block;font-size:.82rem;letter-spacing:.04em;text-transform:uppercase;color:var(--soft);margin-top:.4rem}
.label{font-size:.78rem;letter-spacing:.06em;text-transform:uppercase;color:var(--soft);margin:2rem 0 .5rem;border-top:1px solid var(--line);padding-top:1rem}
.trail{list-style:none;padding:0;margin:0;font-size:.92rem}
.trail li{padding:.25rem 0;color:var(--soft)}
.trail .ok{color:var(--ink)}
.cloud{font-size:.95rem;color:var(--soft)}
.cloud li{margin:.3rem 0}
.next{margin-top:2rem;padding-top:1rem;border-top:1px solid var(--line);font-size:.95rem;color:var(--ink)}
.seal a,.seal{font-size:.8rem;color:var(--soft);word-break:break-all}
"""


def _p(text: str) -> str:
    out = []
    for para in str(text).split("\n"):
        para = para.strip()
        if para:
            out.append(f"<p>{html.escape(para)}</p>")
    return "\n".join(out)


def render(payload: Dict[str, Any], *, title: str = "The Console") -> str:
    """Return a complete, standalone HTML page for one Console answer."""
    parts: List[str] = [f"<h1>{html.escape(title)}</h1>"]

    answer = payload.get("answer")
    if answer:
        parts.append(_p(answer))

    word = payload.get("word") or {}
    if word.get("text"):
        ref = html.escape(str(word.get("ref", "")))
        parts.append(f'<blockquote class="word">{html.escape(str(word["text"]))}'
                     f'<span class="ref">{ref}</span></blockquote>')

    trail = payload.get("trail")
    if trail:
        rows = [f'<div class="label">The trail</div>', '<ul class="trail">']
        door = ((payload.get("next_step") or {}).get("door")) or "CHECK"
        rows.append(f'<li>{html.escape(str(door))}</li>')
        for step in trail:
            status = str(step.get("status", ""))
            cls = " class=\"ok\"" if status == "CONFIRMED" else ""
            dom = html.escape(str(step.get("domain", "")))
            detail = html.escape(str(step.get("detail", "")))
            rows.append(f'<li{cls}>{dom}: {status} — {detail}</li>')
        rows.append("</ul>")
        parts.append("\n".join(rows))

    cloud = payload.get("cloud") or {}
    witnesses = cloud.get("witnesses") or []
    if witnesses:
        rows = ['<div class="label">Beside you</div>', '<ul class="cloud">']
        for w in witnesses[:5]:
            t = html.escape(str(w.get("title") or w.get("witness") or ""))
            shares = html.escape(str(w.get("shares") or ""))
            rows.append(f"<li>{t}{(' — ' + shares) if shares else ''}</li>")
        rows.append("</ul>")
        parts.append("\n".join(rows))

    nxt = payload.get("next_step") or {}
    if nxt.get("do"):
        parts.append(f'<div class="next"><strong>Next.</strong> {html.escape(str(nxt["do"]))}</div>')

    cite = (payload.get("verify") or {}).get("receipt")
    if cite:
        c = html.escape(str(cite))
        href = c if c.startswith("http") else None
        inner = f'<a href="{href}">{c}</a>' if href else c
        parts.append(f'<div class="label">Seal</div><div class="seal">{inner}</div>')

    body = "\n".join(parts)
    return (f"<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
            f"<meta name=\"viewport\" content=\"width=device-width,initial-scale=1,viewport-fit=cover\">"
            f"<title>{html.escape(title)}</title><style>{_CSS}</style></head>"
            f"<body><main>{body}</main></body></html>\n")


def page(text: str, *, client: Any = None, gate_open: bool = False,
         title: Optional[str] = None) -> str:
    """Ask the core and render the answer as a book page, in one call."""
    from . import dispatch
    out = dispatch(text, client=client, gate_open=gate_open)
    return render(out, title=title or "The Console")
