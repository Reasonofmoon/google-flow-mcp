"""File naming, the JSONL generation log, and daily limits."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import config

_UNSAFE = re.compile(r"[^\w\-]+", re.UNICODE)


def slug(prompt: Optional[str], max_len: int = 40) -> str:
    """Short, filesystem-safe summary of a prompt (keeps Korean and other letters)."""
    if not prompt:
        return "untitled"
    words = _UNSAFE.sub(" ", prompt.lower()).split()
    out = ""
    for w in words:
        nxt = f"{out}-{w}" if out else w
        if len(nxt) > max_len:
            break
        out = nxt
    return out or prompt.strip()[:max_len].replace(" ", "-") or "untitled"


def new_path(out: Path, kind: str, prompt: Optional[str], ext: str, index: int | None = None) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = f"_{index}" if index is not None else ""
    path = out / f"{ts}_{kind}_{slug(prompt)}{suffix}.{ext}"
    n = 1
    while path.exists():
        path = out / f"{ts}_{kind}_{slug(prompt)}{suffix}-{n}.{ext}"
        n += 1
    return path


def record(entry: dict) -> None:
    entry = {"ts": datetime.now().isoformat(timespec="seconds"), **entry}
    path = config.log_path()
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _read_today() -> list[dict]:
    path = config.log_path()
    if not path.exists():
        return []
    today = datetime.now().date().isoformat()
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if str(row.get("ts", "")).startswith(today) and row.get("status") == "ok":
                rows.append(row)
    return rows


def usage_today() -> dict:
    rows = _read_today()
    images = sum(int(r.get("count", 0)) for r in rows if r.get("kind") == "image")
    videos = sum(int(r.get("count", 0)) for r in rows if r.get("kind") == "video")
    cost = sum(float(r.get("est_cost_usd") or 0) for r in rows)
    return {"images": images, "videos": videos, "est_cost_usd": round(cost, 4), "calls": len(rows)}


def check_limits(kind: str, count: int, est_cost: float | None) -> None:
    """Raise if this call would go over a daily limit."""
    used = usage_today()
    if kind == "image":
        limit = config.daily_image_limit()
        if limit and used["images"] + count > limit:
            raise RuntimeError(
                f"Daily image limit reached: {used['images']} used + {count} requested > {limit}. "
                "Raise FLOW_DAILY_IMAGE_LIMIT (0 = no limit) or try tomorrow."
            )
    if kind == "video":
        limit = config.daily_video_limit()
        if limit and used["videos"] + count > limit:
            raise RuntimeError(
                f"Daily video limit reached: {used['videos']} used + {count} requested > {limit}. "
                "Raise FLOW_DAILY_VIDEO_LIMIT (0 = no limit) or try tomorrow."
            )
    budget = config.daily_budget_usd()
    if budget and est_cost and used["est_cost_usd"] + est_cost > budget:
        raise RuntimeError(
            f"Daily budget reached: ~${used['est_cost_usd']:.2f} spent + ~${est_cost:.2f} > ${budget:.2f}. "
            "Raise FLOW_DAILY_BUDGET_USD (0 = no limit)."
        )
