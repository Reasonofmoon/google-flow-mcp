"""A self-contained HTML board for a project: ingredients, storyboard, takes, audio, films."""

from __future__ import annotations

from html import escape
from pathlib import Path

from . import project

_CSS = """
:root{color-scheme:light dark;--bg:#f6f6f4;--card:#fff;--ink:#1c1c1e;--mute:#6b6b70;--line:#e2e2de;--accent:#3b6cf6}
@media (prefers-color-scheme:dark){:root{--bg:#141416;--card:#1e1e22;--ink:#f1f1f3;--mute:#9a9aa2;--line:#2e2e34;--accent:#8aa6ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1180px;margin:0 auto;padding:28px 20px 60px}
h1{font-size:26px;margin:0 0 4px}h2{font-size:17px;margin:34px 0 12px;letter-spacing:.02em}
.sub{color:var(--mute);margin:0 0 14px}.pills span{display:inline-block;border:1px solid var(--line);border-radius:999px;padding:2px 10px;margin:0 6px 6px 0;font-size:13px;color:var(--mute)}
.grid{display:grid;gap:14px;grid-template-columns:repeat(auto-fill,minmax(270px,1fr))}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden}
.card img,.card video{display:block;width:100%;background:#000}
.card .body{padding:10px 12px 12px}.card h3{font-size:14px;margin:0 0 4px}
.card p{margin:4px 0;font-size:13px;color:var(--mute)}.card p b{color:var(--ink);font-weight:600}
.tag{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--accent)}
.empty{padding:36px 12px;text-align:center;color:var(--mute);background:repeating-linear-gradient(45deg,transparent,transparent 8px,var(--line) 8px,var(--line) 9px)}
audio{width:100%;margin-top:6px}.film{max-width:720px}.film video{max-height:70vh}
footer{margin-top:40px;color:var(--mute);font-size:12px}
"""


def _media(p: dict, path: str | None, kind: str) -> str:
    if not path or not Path(path).exists():
        return '<div class="empty">not generated yet</div>'
    src = escape(project.rel(p, path), quote=True)
    if kind == "video":
        return f'<video src="{src}" controls preload="metadata"></video>'
    return f'<img src="{src}" loading="lazy" alt="">'


def render(p: dict) -> str:
    e = escape
    parts = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        f"<title>{e(p['title'])} · Flow board</title><style>{_CSS}</style></head><body><main>",
        f"<h1>{e(p['title'])}</h1>",
        f"<p class='sub'>{e(p.get('logline') or '')}</p>",
        "<div class='pills'>",
        f"<span>{e(p['aspect_ratio'])}</span>",
        f"<span>{len(p['shots'])} shots · {sum(s['duration'] for s in p['shots'])}s planned</span>",
        f"<span>estimated spend ~${float(p.get('spent_usd') or 0):.2f}</span>",
    ]
    if p.get("style"):
        parts.append(f"<span>style: {e(p['style'])}</span>")
    parts.append("</div>")

    if p.get("films"):
        film = p["films"][-1]
        parts.append("<h2>Latest film</h2><div class='card film'>")
        parts.append(_media(p, film.get("path"), "video"))
        parts.append(f"<div class='body'><p>{e(Path(film.get('path', '')).name)} · {film.get('duration', '?')}s</p></div></div>")

    if p.get("ingredients"):
        parts.append("<h2>Ingredients</h2><div class='grid'>")
        for k, item in p["ingredients"].items():
            img = (item.get("images") or [None])[0]
            parts.append("<div class='card'>" + _media(p, img, "image"))
            parts.append(f"<div class='body'><span class='tag'>{e(item['kind'])}</span><h3>@{e(k)} · {e(item['name'])}</h3>")
            parts.append(f"<p>{e(item['description'])}</p></div></div>")
        parts.append("</div>")

    parts.append("<h2>Storyboard</h2>")
    if not p["shots"]:
        parts.append("<div class='card'><div class='empty'>no shots planned yet</div></div>")
    else:
        parts.append("<div class='grid'>")
        for s in p["shots"]:
            take = project.selected_take(s)
            parts.append("<div class='card'>")
            parts.append(_media(p, take["path"], "video") if take else _media(p, s.get("keyframe"), "image"))
            parts.append(f"<div class='body'><span class='tag'>shot {s['id']} · {s['duration']}s · {e(s['status'])}</span>")
            parts.append(f"<h3>{e(s['prompt'])}</h3>")
            for label, field in (("Action", "action"), ("Camera", "camera"), ("Dialogue", "dialogue"), ("Sound", "sound")):
                if s.get(field):
                    parts.append(f"<p><b>{label}:</b> {e(s[field])}</p>")
            if take:
                parts.append(f"<p><b>Take:</b> {len(s['takes'])} total · showing {e(take.get('quality', ''))} {e(take.get('resolution', ''))}</p>")
            if s.get("error"):
                parts.append(f"<p><b>Error:</b> {e(s['error'])}</p>")
            parts.append("</div></div>")
        parts.append("</div>")

    audio = p.get("audio") or {}
    if audio.get("music") or audio.get("narration"):
        parts.append("<h2>Audio</h2><div class='grid'>")
        for label in ("music", "narration"):
            item = audio.get(label)
            if item and Path(item.get("path", "")).exists():
                src = escape(project.rel(p, item["path"]), quote=True)
                parts.append(f"<div class='card'><div class='body'><span class='tag'>{label}</span>")
                parts.append(f"<p>{e(item.get('prompt', ''))[:300]}</p><audio controls src='{src}'></audio></div></div>")
        parts.append("</div>")

    parts.append("<footer>Generated locally by google-flow-mcp. AI-generated media carries Google's SynthID watermark.</footer>")
    parts.append("</main></body></html>")
    return "".join(parts)


def write(p: dict) -> Path:
    path = project.dir_of(p["name"]) / "board.html"
    path.write_text(render(p), encoding="utf-8")
    return path
