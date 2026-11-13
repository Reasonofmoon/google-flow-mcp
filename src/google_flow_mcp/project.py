"""Projects: a folder with ingredients, a storyboard, takes, audio and finished films.

Everything lives in plain files under <output>/projects/<name>/ so a project can be
zipped, moved, or inspected without this server.
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import config, ledger

VIDEO_ASPECTS = ("16:9", "9:16")
INGREDIENT_KINDS = ("character", "object", "location", "style")
_TAG = re.compile(r"@([\w\-]+)", re.UNICODE)


def key(name: str) -> str:
    return ledger.slug(name, 48)


def root() -> Path:
    return config.projects_dir()


def dir_of(name: str) -> Path:
    return root() / key(name)


def _file(name: str) -> Path:
    return dir_of(name) / "project.json"


def exists(name: str) -> bool:
    return _file(name).exists()


def list_names() -> list[str]:
    return sorted(p.parent.name for p in root().glob("*/project.json"))


def set_active(name: str) -> None:
    (root() / ".active").write_text(key(name), encoding="utf-8")


def active_name() -> Optional[str]:
    marker = root() / ".active"
    if not marker.exists():
        return None
    name = marker.read_text(encoding="utf-8").strip()
    return name if name and exists(name) else None


def create(name: str, title: Optional[str] = None, logline: Optional[str] = None,
           aspect_ratio: str = "16:9", style: Optional[str] = None) -> dict:
    if aspect_ratio not in VIDEO_ASPECTS:
        raise ValueError(f"aspect_ratio must be one of {VIDEO_ASPECTS}; got {aspect_ratio}.")
    p = {
        "name": key(name),
        "title": title or name,
        "logline": logline or "",
        "aspect_ratio": aspect_ratio,
        "style": style or "",
        "created": datetime.now().isoformat(timespec="seconds"),
        "ingredients": {},
        "shots": [],
        "audio": {},
        "films": [],
        "spent_usd": 0.0,
    }
    dir_of(name).mkdir(parents=True, exist_ok=True)
    save(p)
    return p


def load(name: Optional[str] = None) -> dict:
    name = name or active_name()
    if not name:
        raise ValueError("No active project. Call flow_project(name=\"my-film\") first.")
    if not exists(name):
        raise ValueError(f"Project '{name}' not found. Existing: {', '.join(list_names()) or 'none'}.")
    return json.loads(_file(name).read_text(encoding="utf-8"))


def save(p: dict) -> None:
    path = _file(p["name"])
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(p, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def sub(p: dict, folder: str) -> Path:
    path = dir_of(p["name"]) / folder
    path.mkdir(parents=True, exist_ok=True)
    return path


def rel(p: dict, path: str | Path) -> str:
    """Path relative to the project folder (for the HTML board), else a file URI."""
    try:
        return Path(path).resolve().relative_to(dir_of(p["name"]).resolve()).as_posix()
    except ValueError:
        return Path(path).resolve().as_uri()


def add_spend(p: dict, usd: Optional[float]) -> None:
    p["spent_usd"] = round(float(p.get("spent_usd") or 0) + float(usd or 0), 4)


# ── Ingredients ───────────────────────────────────────────────────────────────


def find_tags(text: Optional[str]) -> list[str]:
    seen: list[str] = []
    for t in _TAG.findall(text or ""):
        k = key(t)
        if k not in seen:
            seen.append(k)
    return seen


def save_ingredient(p: dict, name: str, description: str, kind: str = "character",
                    image_paths: Optional[list[str]] = None) -> dict:
    if kind not in INGREDIENT_KINDS:
        raise ValueError(f"kind must be one of {INGREDIENT_KINDS}; got {kind}.")
    k = key(name)
    folder = sub(p, "ingredients")
    stored: list[str] = list(p["ingredients"].get(k, {}).get("images", [])) if not image_paths else []
    for i, src in enumerate(image_paths or []):
        src_path = Path(src).expanduser()
        if not src_path.is_file():
            raise ValueError(f"Reference image not found: {src}")
        dest = folder / f"{k}_{i + 1}{src_path.suffix.lower() or '.png'}"
        if src_path.resolve() != dest.resolve():
            shutil.copyfile(src_path, dest)
        stored.append(str(dest))
    item = {"name": name, "kind": kind, "description": description.strip(), "images": stored}
    p["ingredients"][k] = item
    return item


def expand(p: Optional[dict], text: str, extra: Optional[list[str]] = None,
           max_images: int = 6, per_ingredient: int = 2, offset: int = 0) -> tuple[str, list[str], list[str]]:
    """Resolve @tags (and `extra` names) to reference images plus a short legend.

    Returns (prompt text, image paths in legend order, ingredient keys used).
    Unknown @tags are left untouched, so plain '@' in a prompt does no harm.
    """
    if not p or not p.get("ingredients"):
        return text, [], []
    names = find_tags(text) + [key(n) for n in (extra or [])]
    used: list[str] = []
    for n in names:
        if n in p["ingredients"] and n not in used:
            used.append(n)
    if not used:
        return text, [], []

    def _swap(match: re.Match) -> str:
        item = p["ingredients"].get(key(match.group(1)))
        return item["name"] if item else match.group(0)

    out = _TAG.sub(_swap, text)
    images: list[str] = []
    legend: list[str] = []
    for n in used:
        item = p["ingredients"][n]
        take = [i for i in item.get("images", []) if Path(i).is_file()][:per_ingredient]
        take = take[: max(0, max_images - len(images))]
        if take:
            first = offset + len(images) + 1
            where = f"image {first}" if len(take) == 1 else f"images {first}-{first + len(take) - 1}"
            images += take
            legend.append(f"- {where}: {item['name']} ({item['kind']}) — {item['description']}")
        else:
            legend.append(f"- {item['name']} ({item['kind']}, no image) — {item['description']}")
    if images:
        out += "\n\nReference images, in the order attached. Keep each one's look consistent:\n"
    else:
        out += "\n\nKeep these consistent:\n"
    return out + "\n".join(legend), images, used


# ── Shots ─────────────────────────────────────────────────────────────────────


def new_shot(shot_id: int, data: dict) -> dict:
    prompt = str(data.get("prompt") or "").strip()
    if not prompt:
        raise ValueError(f"Shot {shot_id} needs a 'prompt' (what we see).")
    return {
        "id": shot_id,
        "prompt": prompt,
        "action": str(data.get("action") or "").strip(),
        "duration": max(3, min(15, int(data.get("duration") or 5))),
        "camera": str(data.get("camera") or "").strip(),
        "dialogue": str(data.get("dialogue") or "").strip(),
        "sound": str(data.get("sound") or "").strip(),
        "ingredients": [key(n) for n in (data.get("ingredients") or [])],
        "keyframe": None,
        "takes": [],
        "selected_take": None,
        "trim": [None, None],
        "status": "planned",
        "error": "",
    }


def get_shot(p: dict, shot_id: int) -> dict:
    for s in p["shots"]:
        if s["id"] == int(shot_id):
            return s
    raise ValueError(f"Shot {shot_id} not found. Shots: {[s['id'] for s in p['shots']] or 'none'}.")


def selected_take(shot: dict) -> Optional[dict]:
    takes = shot.get("takes") or []
    if not takes:
        return None
    i = shot.get("selected_take")
    return takes[i] if isinstance(i, int) and 0 <= i < len(takes) else takes[-1]


def shot_ingredients(p: dict, shot: dict) -> list[str]:
    names = list(shot.get("ingredients") or [])
    for t in find_tags(shot["prompt"]) + find_tags(shot.get("action")) + find_tags(shot.get("dialogue")):
        if t not in names:
            names.append(t)
    return names


def next_step(p: dict) -> str:
    shots = p["shots"]
    if not shots:
        return "Plan the storyboard with flow_storyboard_plan (add ingredients first with flow_ingredient_save if characters must stay consistent)."
    if any(not s.get("keyframe") for s in shots):
        return "Generate keyframes with flow_storyboard_keyframes, then look at them before spending on video."
    if any(s.get("status") == "rendering" for s in shots):
        return "Shots are still rendering in the background. Call flow_project again in a minute."
    if any(not s.get("takes") for s in shots):
        return "Render the shots with flow_storyboard_render (quality='draft' is 360p and about one third of the 720p price)."
    if not p.get("films"):
        return "Join the takes with flow_assemble (add music or narration first if you want them)."
    return "Film assembled. Use flow_review to check it, flow_shot_update / flow_edit_video to fix shots, or re-render at quality='standard'."
