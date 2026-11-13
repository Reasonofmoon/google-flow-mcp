"""Studio tools: projects, ingredients, storyboard, background renders, audio, assembly, review.

These mirror how Google Flow is used (ingredients, frames to video, scene building, extend
and edit), but run on the Gemini API and keep everything in a local project folder.
"""

from __future__ import annotations

import asyncio
import math
import tempfile
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from . import board, config, ledger, media, presets, pricing, project
from . import server as core

mcp = core.mcp

QUALITY = {"draft": "360p", "standard": "720p", "high": "1080p"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
_SHEET_PROMPTS = {
    "character": "Character reference sheet of {d}. Three views side by side on a plain light-grey "
                 "background: front view, three-quarter view and side view, full body, same outfit "
                 "and proportions in every view. No text, no labels.",
    "object": "Product reference sheet of {d}. Three views side by side on a plain light-grey "
              "background: front, three-quarter and top view, consistent materials and colors. "
              "No text, no labels.",
    "location": "Establishing wide shot of {d}. Clear view of the whole place, even lighting, "
                "no people, no text.",
    "style": "Style reference image: {d}. A simple scene that shows the palette, lighting, "
             "texture and line quality clearly. No text.",
}

# (project name, shot id) -> running render task
_jobs: dict[tuple[str, int], asyncio.Task] = {}


# ── Helpers ───────────────────────────────────────────────────────────────────


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _swallow(task: asyncio.Task) -> None:
    if not task.cancelled():
        task.exception()


def _running(name: str, shot_id: int) -> bool:
    task = _jobs.get((name, shot_id))
    return bool(task and not task.done())


def _sync_jobs(p: dict) -> bool:
    """Shots marked 'rendering' with no live task were interrupted (e.g. server restart)."""
    changed = False
    for s in p["shots"]:
        if s.get("status") == "rendering" and not _running(p["name"], s["id"]):
            s["status"] = "rendered" if s.get("takes") else ("keyframed" if s.get("keyframe") else "planned")
            s["error"] = "render was interrupted; run flow_storyboard_render again for this shot"
            changed = True
    if changed:
        project.save(p)
    return changed


def _optional_project(name: Optional[str], attach: bool) -> Optional[dict]:
    if not attach:
        return None
    return project.load(name) if name else core._active_project()


def _sheet(items: list[tuple[str, Optional[str]]], cols: int = 3) -> list[bytes]:
    if not config.inline_preview():
        return []
    if not any(path and media.safe_thumbnail(path, 64) is not None for _, path in items):
        return []
    return [media.contact_sheet(items, cols=cols)]


def _ids(p: dict, shots: Optional[list[int]]) -> list[int]:
    if not shots:
        return [s["id"] for s in p["shots"]]
    return [project.get_shot(p, int(i))["id"] for i in shots]


def _status_text(p: dict) -> str:
    lines = [
        f"Project: {p['title']} ({p['name']}) · {p['aspect_ratio']}" + (f" · style: {p['style']}" if p.get("style") else ""),
        f"Folder: {project.dir_of(p['name'])}",
    ]
    if p.get("logline"):
        lines.append(f"Logline: {p['logline']}")
    ing = p.get("ingredients") or {}
    lines.append(f"Ingredients ({len(ing)}): " + (", ".join(
        f"@{k} ({v['kind']}, {len(v.get('images') or [])} image(s))" for k, v in ing.items()) or "none"))
    shots = p["shots"]
    lines.append(f"Storyboard: {len(shots)} shot(s), {sum(s['duration'] for s in shots)}s planned")
    for s in shots:
        takes = ", ".join(f"{i + 1}:{t.get('quality')}" for i, t in enumerate(s.get("takes") or [])) or "none"
        sel = s.get("selected_take")
        trim = s.get("trim") or [None, None]
        extra = f" · trim {trim[0] or 0}-{trim[1] or 'end'}s" if trim[0] or trim[1] else ""
        err = f" · ERROR: {s['error']}" if s.get("error") else ""
        lines.append(
            f"  {s['id']}. [{s['status']}] {s['duration']}s"
            + (f" · {s['camera']}" if s.get("camera") else "")
            + f" · keyframe {'yes' if s.get('keyframe') else 'no'} · takes {takes}"
            + (f" (using {sel + 1})" if isinstance(sel, int) else "") + extra + err
            + f"\n     {s['prompt']}"
        )
    audio = p.get("audio") or {}
    lines.append(f"Audio: music {'yes' if audio.get('music') else 'no'}, narration {'yes' if audio.get('narration') else 'no'}")
    films = p.get("films") or []
    lines.append(f"Films: {len(films)}" + (f" (latest: {films[-1]['path']})" if films else ""))
    lines.append(f"Estimated spend on this project: ~${float(p.get('spent_usd') or 0):.2f}")
    lines.append(f"Next: {project.next_step(p)}")
    return "\n".join(lines) + core.demo_note()


# ── Project + ingredients ─────────────────────────────────────────────────────


@core.tool()
async def flow_project(
    name: Optional[str] = None,
    title: Optional[str] = None,
    logline: Optional[str] = None,
    aspect_ratio: Optional[str] = None,
    style: Optional[str] = None,
) -> str:
    """
    Create or open a project (it becomes the active one), or show the active project's status.

    A project is a folder holding ingredients, a storyboard, takes, audio and finished films.

    Args:
        name: Project name. New name = create; existing name = open. Omit to see the status.
        title: Display title.
        logline: One-sentence summary of the piece.
        aspect_ratio: '16:9' (default) or '9:16' for Shorts/Reels.
        style: A look applied to every shot, e.g. 'warm watercolor picture book'.
    """
    if name:
        if project.exists(name):
            p = project.load(name)
            if aspect_ratio:
                if aspect_ratio not in project.VIDEO_ASPECTS:
                    raise ValueError(f"aspect_ratio must be one of {project.VIDEO_ASPECTS}.")
                p["aspect_ratio"] = aspect_ratio
            for field, value in (("title", title), ("logline", logline), ("style", style)):
                if value is not None:
                    p[field] = value
            project.save(p)
        else:
            p = project.create(name, title, logline, aspect_ratio or "16:9", style)
        project.set_active(p["name"])
    else:
        p = core._active_project()
        if not p:
            names = project.list_names()
            return ("No active project. " + (f"Existing projects: {', '.join(names)}. " if names else "")
                    + "Create one with flow_project(name='my-film', aspect_ratio='16:9').")
    _sync_jobs(p)
    board.write(p)
    others = [n for n in project.list_names() if n != p["name"]]
    return _status_text(p) + (f"\nOther projects: {', '.join(others)}" if others else "")


@core.tool()
async def flow_ingredient_save(
    name: str,
    description: str,
    kind: str = "character",
    image_paths: Optional[list[str]] = None,
    generate: bool = False,
    model: Optional[str] = None,
    project_name: Optional[str] = None,
) -> Any:
    """
    Save a reusable ingredient (character, object, location or style) in the project.

    Afterwards write @name in any prompt (image, video, storyboard shot) and its reference
    images and description are attached automatically, which keeps the look consistent.

    Args:
        name: Short handle, e.g. 'mira'. Used as @mira.
        description: What must stay the same (face, hair, clothes, colors, materials...).
        kind: 'character', 'object', 'location' or 'style'.
        image_paths: 1-3 existing reference images (copied into the project).
        generate: If true and no images are given, generate a reference sheet from the description.
        model: Image model for generate ('fast' default, 'pro' for more detail).
        project_name: Project to use (default: active project).
    """
    p = project.load(project_name)
    k = project.key(name)
    item = project.save_ingredient(p, name, description, kind, image_paths)
    project.save(p)
    note = ""
    if generate and not item["images"]:
        model_id = config.image_model(model)
        prompt = _SHEET_PROMPTS[kind].format(d=description.strip())
        if p.get("style"):
            prompt += f" Style: {p['style']}."
        est = pricing.image_cost(model_id, "2K", 1)
        out = project.sub(p, "ingredients")
        aspect = "1:1" if kind == "style" else "16:9"
        paths, _ = await core._tracked(
            tool="flow_ingredient_save", kind="image", count=1, model=model_id, prompt=prompt,
            params={"project": p["name"], "ingredient": k, "kind": kind}, est_cost=est,
            work=lambda: core._images(model=model_id, input_=prompt, n=1, aspect_ratio=aspect,
                                      image_size="2K", out=out, kind=k, prompt="reference sheet"),
        )
        p = project.load(p["name"])
        p["ingredients"][k]["images"] = paths
        project.add_spend(p, core.billed(est))
        project.save(p)
        item = p["ingredients"][k]
        note = f" Generated a reference sheet ({pricing.fmt_usd(est)})."
    board.write(p)
    text = (f"Saved ingredient @{k} ({kind}) with {len(item['images'])} image(s).{note}\n"
            f"Use it by writing @{k} in a prompt." + ("\n" + "\n".join(item["images"]) if item["images"] else
            "\nNo reference image yet: add image_paths or call again with generate=true for stronger consistency."))
    return core._reply(text, core._previews(item["images"][:1]))


# ── Storyboard ────────────────────────────────────────────────────────────────


def _plan_costs(p: dict, shots: list[dict]) -> str:
    n = len(shots)
    secs = sum(s["duration"] for s in shots)
    key = pricing.image_cost(config.image_model("fast"), "1K", n)
    vm = config.video_model()
    draft = pricing.video_cost(vm, secs, "360p")
    std = pricing.video_cost(vm, secs, "720p")
    return (f"Estimated cost: keyframes {pricing.fmt_usd(key)}, draft render (360p) {pricing.fmt_usd(draft)}, "
            f"standard render (720p) {pricing.fmt_usd(std)}.")


@core.tool()
async def flow_storyboard_plan(
    shots: list[dict],
    mode: str = "replace",
    project_name: Optional[str] = None,
) -> str:
    """
    Set the storyboard: an ordered list of shots. Nothing is generated yet.

    Each shot is an object with:
      prompt (required): what we see: subject, place, light. Use @name for ingredients.
      action: what moves or happens during the shot.
      duration: seconds, 3-15 (default 5).
      camera: a camera preset ('push-in', 'orbit', 'drone', ...) or your own words.
      dialogue: spoken line(s), e.g. 'Mira says: "We made it."'
      sound: sound design, e.g. 'soft rain, distant thunder, no music'.
      ingredients: extra ingredient names to attach besides the @tags.

    Args:
        shots: The shot list.
        mode: 'replace' (default; refuses if existing shots already have keyframes or takes),
              'append' (add to the end) or 'reset' (drop the old plan; files stay on disk).
        project_name: Project to use (default: active project).
    """
    if mode not in ("replace", "append", "reset"):
        raise ValueError("mode must be 'replace', 'append' or 'reset'.")
    if not shots:
        raise ValueError("Give at least one shot.")
    p = project.load(project_name)
    has_assets = any(s.get("keyframe") or s.get("takes") for s in p["shots"])
    if mode == "replace" and has_assets:
        raise ValueError(
            "This storyboard already has keyframes or takes. Use mode='append' to add shots, "
            "flow_shot_update to change one shot, or mode='reset' to start the plan over "
            "(generated files stay in the project folder)."
        )
    existing = p["shots"] if mode == "append" else []
    start = max((s["id"] for s in existing), default=0)
    new = [project.new_shot(start + i + 1, data) for i, data in enumerate(shots)]
    warnings: list[str] = []
    for s in new:
        for n in s["ingredients"]:
            if n not in p["ingredients"]:
                raise ValueError(f"Shot {s['id']}: ingredient '{n}' is not saved. Saved: {', '.join(p['ingredients']) or 'none'}.")
        unknown = [t for t in project.shot_ingredients(p, s) if t not in p["ingredients"]]
        if unknown:
            warnings.append(f"Shot {s['id']}: @{', @'.join(unknown)} not saved as ingredient(s); the tag will be read as plain text.")
    p["shots"] = existing + new
    project.save(p)
    board.write(p)
    lines = [f"Storyboard set: {len(p['shots'])} shot(s), {sum(s['duration'] for s in p['shots'])}s."]
    for s in p["shots"]:
        lines.append(f"  {s['id']}. {s['duration']}s" + (f" · {s['camera']}" if s["camera"] else "") + f" · {s['prompt']}")
    lines.append(_plan_costs(p, p["shots"]))
    lines += warnings
    lines.append("Next: flow_storyboard_keyframes (cheap stills to check the look before video).")
    return "\n".join(lines)


@core.tool()
async def flow_shot_update(
    shot: int,
    prompt: Optional[str] = None,
    action: Optional[str] = None,
    duration: Optional[int] = None,
    camera: Optional[str] = None,
    dialogue: Optional[str] = None,
    sound: Optional[str] = None,
    ingredients: Optional[list[str]] = None,
    select_take: Optional[int] = None,
    trim_start: Optional[float] = None,
    trim_end: Optional[float] = None,
    project_name: Optional[str] = None,
) -> str:
    """
    Change one shot: its text, which take is used, or where it is trimmed in the final cut.

    Changing prompt or ingredients clears the keyframe so it is regenerated next time.

    Args:
        shot: Shot number.
        prompt / action / duration / camera / dialogue / sound / ingredients: new values.
        select_take: Take number (1 = first) to use in flow_assemble.
        trim_start: Seconds to cut from the start of the take in the final cut (0 = none).
        trim_end: Second at which the take ends in the final cut (0 = until the end).
        project_name: Project to use (default: active project).
    """
    p = project.load(project_name)
    s = project.get_shot(p, shot)
    changed: list[str] = []
    look_changed = False
    if prompt is not None and prompt.strip() and prompt.strip() != s["prompt"]:
        s["prompt"] = prompt.strip()
        look_changed = True
        changed.append("prompt")
    if ingredients is not None:
        keys = [project.key(n) for n in ingredients]
        for n in keys:
            if n not in p["ingredients"]:
                raise ValueError(f"Ingredient '{n}' is not saved. Saved: {', '.join(p['ingredients']) or 'none'}.")
        s["ingredients"] = keys
        look_changed = True
        changed.append("ingredients")
    for field, value in (("action", action), ("camera", camera), ("dialogue", dialogue), ("sound", sound)):
        if value is not None:
            s[field] = value.strip()
            changed.append(field)
    if duration is not None:
        s["duration"] = max(3, min(15, int(duration)))
        changed.append("duration")
    if select_take is not None:
        if not 1 <= select_take <= len(s["takes"]):
            raise ValueError(f"Shot {shot} has {len(s['takes'])} take(s).")
        s["selected_take"] = select_take - 1
        changed.append(f"using take {select_take}")
    if trim_start is not None:
        s["trim"][0] = float(trim_start) if trim_start > 0 else None
        changed.append("trim start")
    if trim_end is not None:
        s["trim"][1] = float(trim_end) if trim_end > 0 else None
        changed.append("trim end")
    if look_changed and s.get("keyframe"):
        s["keyframe"] = None
        if not s["takes"]:
            s["status"] = "planned"
        changed.append("keyframe cleared (regenerate with flow_storyboard_keyframes)")
    if not changed:
        return f"Shot {shot}: nothing changed."
    project.save(p)
    board.write(p)
    return f"Shot {shot} updated: {', '.join(changed)}."


@core.tool()
async def flow_storyboard_keyframes(
    shots: Optional[list[int]] = None,
    model: Optional[str] = None,
    image_size: str = "1K",
    redo: bool = False,
    project_name: Optional[str] = None,
) -> Any:
    """
    Generate one still image (keyframe) per shot and return a contact sheet to look at.

    Keyframes are cheap (about $0.03 each with the fast model) and become the first frame of
    each video, so fix the look here before paying for video.

    Args:
        shots: Shot numbers. Default: shots without a keyframe (all shots if redo=true).
        model: 'fast' (default), 'pro' or 'lite'.
        image_size: '1K' (default) or '2K'.
        redo: Regenerate keyframes that already exist.
        project_name: Project to use (default: active project).
    """
    p = project.load(project_name)
    name = p["name"]
    if not p["shots"]:
        raise ValueError("No shots yet. Call flow_storyboard_plan first.")
    targets = _ids(p, shots) if shots else [s["id"] for s in p["shots"] if redo or not s.get("keyframe")]
    if not targets:
        return core._reply("All shots already have keyframes (use redo=true to regenerate).\n" + project.next_step(p),
                           _sheet([(f"S{s['id']}", s.get("keyframe")) for s in p["shots"]]))
    model_id = config.image_model(model)
    each = pricing.image_cost(model_id, image_size, 1)
    ledger.check_limits("image", len(targets), None if each is None else each * len(targets))
    sem = asyncio.Semaphore(3)

    async def one(shot_id: int) -> str:
        async with sem:
            pj = project.load(name)
            s = project.get_shot(pj, shot_id)
            text = s["prompt"] + (f"\nStyle: {pj['style']}." if pj.get("style") else "")
            text += "\nA single cinematic film frame. No captions, subtitles, watermarks or borders."
            text, refs, used = project.expand(pj, text, extra=s["ingredients"], max_images=14, per_ingredient=3)
            input_: Any = text if not refs else [{"type": "text", "text": text}, *(core._image_part(r) for r in refs)]
            out = project.sub(pj, "keyframes")
            paths, _ = await core._tracked(
                tool="flow_storyboard_keyframes", kind="image", count=1, model=model_id, prompt=s["prompt"],
                params={"project": name, "shot": shot_id, "ingredients": used, "image_size": image_size},
                est_cost=each,
                work=lambda: core._images(model=model_id, input_=input_, n=1, aspect_ratio=pj["aspect_ratio"],
                                          image_size=image_size, out=out, kind=f"s{shot_id:02d}", prompt=s["prompt"]),
            )
            pj = project.load(name)
            s = project.get_shot(pj, shot_id)
            s["keyframe"] = paths[0]
            s["error"] = ""
            if s["status"] in ("planned", "error"):
                s["status"] = "keyframed"
            project.add_spend(pj, core.billed(each))
            project.save(pj)
            return paths[0]

    results = await asyncio.gather(*(one(i) for i in targets), return_exceptions=True)
    p = project.load(name)
    lines = []
    ok = 0
    for shot_id, res in zip(targets, results):
        if isinstance(res, Exception):
            s = project.get_shot(p, shot_id)
            s["error"] = f"keyframe failed: {res}"[:300]
            lines.append(f"  shot {shot_id}: FAILED: {res}")
        else:
            ok += 1
            lines.append(f"  shot {shot_id}: {res}")
    project.save(p)
    board.write(p)
    cost = pricing.fmt_usd(None if each is None else each * ok)
    head = f"Keyframes: {ok}/{len(targets)} generated with {model_id} ({cost})."
    tail = ("Look at the sheet. Fix weak shots with flow_shot_update + flow_storyboard_keyframes(shots=[n]), "
            "then render with flow_storyboard_render(quality='draft').")
    return core._reply("\n".join([head, *lines, tail]),
                       _sheet([(f"S{s['id']}", s.get("keyframe")) for s in p["shots"]]))


def _shot_prompt(p: dict, s: dict, has_keyframe: bool) -> str:
    parts = []
    if has_keyframe:
        parts.append("Start exactly from the first attached image; it is the first frame of the video.")
    parts.append(s["prompt"])
    if s.get("action"):
        parts.append(s["action"])
    if s.get("camera"):
        parts.append(f"Camera: {presets.camera_phrase(s['camera'])}.")
    if s.get("dialogue"):
        parts.append(f"Dialogue: {s['dialogue']}")
    if s.get("sound"):
        parts.append(f"Sound: {s['sound']}")
    if p.get("style"):
        parts.append(f"Style: {p['style']}.")
    parts.append("Single continuous shot, no scene cuts. No captions or subtitles.")
    return "\n".join(parts)


async def _render_one(name: str, shot_id: int, quality: str, resolution: str, sem: asyncio.Semaphore) -> str:
    async with sem:
        p = project.load(name)
        s = project.get_shot(p, shot_id)
        model_id = config.video_model()
        keyframe = s.get("keyframe") if s.get("keyframe") and Path(s["keyframe"]).is_file() else None
        offset = 1 if keyframe else 0
        text, refs, used = project.expand(p, _shot_prompt(p, s, bool(keyframe)), extra=s["ingredients"],
                                          max_images=6 - offset, per_ingredient=2, offset=offset)
        images = ([keyframe] if keyframe else []) + refs
        input_: Any = text if not images else [*(core._image_part(i) for i in images), {"type": "text", "text": text}]
        out = project.sub(p, "shots")
        est = pricing.video_cost(model_id, s["duration"], resolution)
        fmt = core._video_format(s["duration"], p["aspect_ratio"], resolution)
        try:
            paths, extra = await core._tracked(
                tool="flow_storyboard_render", kind="video", count=1, model=model_id, prompt=s["prompt"],
                params={"project": name, "shot": shot_id, "quality": quality, "resolution": resolution,
                        "duration": s["duration"], "keyframe": keyframe, "ingredients": used},
                est_cost=est,
                work=lambda: core._video(model=model_id, input_=input_, response_format=fmt, out=out,
                                         kind=f"s{shot_id:02d}-{quality}", prompt=s["prompt"]),
            )
        except Exception as exc:
            p = project.load(name)
            s = project.get_shot(p, shot_id)
            s["status"] = "error"
            s["error"] = f"{type(exc).__name__}: {exc}"[:300]
            project.save(p)
            board.write(p)
            raise
        p = project.load(name)
        s = project.get_shot(p, shot_id)
        s["takes"].append({"path": paths[0], "quality": quality, "resolution": resolution,
                           "interaction_id": extra.get("interaction_id"), "ts": _now(), "est_cost_usd": est})
        s["selected_take"] = len(s["takes"]) - 1
        s["status"] = "rendered"
        s["error"] = ""
        project.add_spend(p, core.billed(est))
        project.save(p)
        board.write(p)
        return paths[0]


@core.tool()
async def flow_storyboard_render(
    shots: Optional[list[int]] = None,
    quality: str = "draft",
    confirm_cost: bool = False,
    wait_seconds: Optional[int] = None,
    project_name: Optional[str] = None,
) -> Any:
    """
    Render storyboard shots to video (keyframe = first frame, ingredients = references).

    Shots render in parallel as background jobs. The call waits up to wait_seconds and then
    returns; unfinished shots keep rendering, and flow_project shows their progress.
    A standard/high render is a new generation from the same keyframe, so motion can differ
    from the draft while the look stays the same.

    Args:
        shots: Shot numbers. Default: every shot without a take at this quality.
        quality: 'draft' (360p, cheapest, for checking motion), 'standard' (720p) or 'high' (1080p).
        confirm_cost: Set true only after the user accepted the cost estimate.
        wait_seconds: How long to wait before returning (default 150).
        project_name: Project to use (default: active project).
    """
    if quality not in QUALITY:
        raise ValueError(f"quality must be one of {sorted(QUALITY)}; got {quality}.")
    resolution = QUALITY[quality]
    p = project.load(project_name)
    name = p["name"]
    _sync_jobs(p)
    if not p["shots"]:
        raise ValueError("No shots yet. Call flow_storyboard_plan first.")
    wanted = _ids(p, shots) if shots else [
        s["id"] for s in p["shots"] if not any(t.get("quality") == quality for t in s.get("takes") or [])]
    busy = [i for i in wanted if _running(name, i)]
    ids = [i for i in wanted if i not in busy]
    if not ids:
        return ("Nothing to start: " + (f"shot(s) {busy} are already rendering." if busy else
                f"every shot already has a {quality} take (pass shots=[...] to render again)."))
    model_id = config.video_model()
    secs = sum(project.get_shot(p, i)["duration"] for i in ids)
    costs = [pricing.video_cost(model_id, project.get_shot(p, i)["duration"], resolution) for i in ids]
    total = None if any(c is None for c in costs) else round(sum(costs), 4)
    gate = core._cost_gate(total, f"{len(ids)} shot(s), {secs}s at {resolution} with {model_id}", confirm_cost)
    if gate:
        return gate
    ledger.check_limits("video", len(ids), total)

    for i in ids:
        s = project.get_shot(p, i)
        s["status"] = "rendering"
        s["error"] = ""
    project.save(p)
    sem = asyncio.Semaphore(config.render_concurrency())
    tasks: dict[int, asyncio.Task] = {}
    for i in ids:
        task = asyncio.create_task(_render_one(name, i, quality, resolution, sem))
        task.add_done_callback(_swallow)
        _jobs[(name, i)] = task
        tasks[i] = task
    wait = config.render_wait_seconds() if wait_seconds is None else wait_seconds
    await asyncio.wait(tasks.values(), timeout=max(1, wait))

    p = project.load(name)
    lines = [f"Render {quality} ({resolution}) of {len(ids)} shot(s), estimated {pricing.fmt_usd(total)}:"]
    done_paths: list[tuple[str, Optional[str]]] = []
    pending = 0
    for i, task in tasks.items():
        if not task.done():
            pending += 1
            lines.append(f"  shot {i}: still rendering in the background")
        elif task.cancelled():
            lines.append(f"  shot {i}: cancelled")
        elif task.exception():
            lines.append(f"  shot {i}: FAILED: {task.exception()}")
        else:
            lines.append(f"  shot {i}: {task.result()}")
            done_paths.append((f"S{i}", task.result()))
    if pending:
        lines.append(f"{pending} shot(s) still rendering. Call flow_project in a minute to check; do not start them again.")
    else:
        lines.append("Next: flow_review a take, fix shots with flow_shot_update or flow_edit_video, then flow_assemble.")
    if busy:
        lines.append(f"Skipped {busy}: already rendering.")
    board.write(p)

    previews: list[bytes] = []
    if done_paths and config.inline_preview() and media.ffmpeg_exe():
        try:
            with tempfile.TemporaryDirectory(prefix="flow_mid_") as td:
                stills = []
                for label, path in done_paths:
                    still = await media.middle_frame(path, Path(td) / f"{label}.jpg")
                    stills.append((f"{label} mid-frame", str(still) if still else None))
                previews = _sheet(stills)
        except Exception:
            previews = []
    return core._reply("\n".join(lines), previews)


# ── Editing, audio, assembly ──────────────────────────────────────────────────


@core.tool()
async def flow_edit_video(
    prompt: str,
    shot: Optional[int] = None,
    video_path: Optional[str] = None,
    previous_interaction_id: Optional[str] = None,
    resolution: Optional[str] = None,
    keep_rest: bool = True,
    confirm_cost: bool = False,
    project_name: Optional[str] = None,
) -> str:
    """
    Edit a video with a short instruction: add or remove an object, restyle, relight.

    Keep the prompt short ('Make the jacket red', 'Add light snowfall', 'Make this anime').
    Give ONE source: a storyboard shot (the edit becomes a new take), a local video of 15 s
    or less, or a previous_interaction_id from an earlier video result.

    Args:
        prompt: The change to make.
        shot: Storyboard shot number to edit (uses its selected take).
        video_path: Local MP4 to edit.
        previous_interaction_id: interaction_id from an earlier video tool result.
        resolution: '360p', '720p', '1080p' or '4k' (default: same as the shot's take, else 720p).
        keep_rest: Add 'Keep everything else the same.' (recommended).
        confirm_cost: Set true only after the user accepted the cost estimate.
        project_name: Project to use when shot is given (default: active project).
    """
    if sum(x is not None for x in (shot, video_path, previous_interaction_id)) != 1:
        raise ValueError("Give exactly one of shot, video_path or previous_interaction_id.")
    p = None
    seconds = 10.0
    src = video_path
    prev = previous_interaction_id
    aspect: Optional[str] = None
    if shot is not None:
        p = project.load(project_name)
        s = project.get_shot(p, shot)
        take = project.selected_take(s)
        if not take:
            raise ValueError(f"Shot {shot} has no take yet. Render it first.")
        src, prev, seconds = take["path"], take.get("interaction_id"), float(s["duration"])
        resolution = resolution or take.get("resolution")
        aspect = p["aspect_ratio"]  # keep a vertical project vertical
        out = project.sub(p, "shots")
        kind = f"s{int(shot):02d}-edit"
    else:
        out = config.output_dir()
        kind = "edit"
        if src:
            if not Path(src).expanduser().is_file():
                raise ValueError(f"Video not found: {src}")
            if media.ffmpeg_exe():
                seconds = (await media.probe(Path(src).expanduser()))["duration"] or 10.0
                aspect = await core.clip_aspect(src)
    resolution = resolution or "720p"
    if resolution not in core.VIDEO_RESOLUTIONS:
        raise ValueError(f"resolution must be one of {core.VIDEO_RESOLUTIONS}; got {resolution}.")
    text = prompt.strip()
    if keep_rest and "keep everything" not in text.lower():
        text += " Keep everything else the same."
    model_id = config.video_model()
    est = pricing.video_cost(model_id, math.ceil(seconds), resolution)
    gate = core._cost_gate(est, f"editing ~{math.ceil(seconds)}s at {resolution} with {model_id}", confirm_cost)
    if gate:
        return gate
    fmt: dict = {"type": "video", "resolution": resolution}
    if aspect:
        fmt["aspect_ratio"] = aspect
    if resolution in ("1080p", "4k"):
        fmt["delivery"] = "uri"

    async def work() -> tuple[list[str], dict]:
        if prev:
            try:
                return await core._video(model=model_id, input_=text, response_format=fmt, out=out,
                                         kind=kind, prompt=prompt, previous_interaction_id=prev)
            except Exception:
                if not src:
                    raise
        uploaded = await core._upload(core.get_client(), src)
        input_ = [{"type": "video", "uri": uploaded.uri}, {"type": "text", "text": text}]
        return await core._video(model=model_id, input_=input_, response_format=fmt, out=out, kind=kind, prompt=prompt)

    paths, extra = await core._tracked(
        tool="flow_edit_video", kind="video", count=1, model=model_id, prompt=prompt,
        params={"project": p["name"] if p else None, "shot": shot, "source": src,
                "previous_interaction_id": prev, "resolution": resolution},
        est_cost=est, work=work,
    )
    if p:
        p = project.load(p["name"])
        s = project.get_shot(p, shot)
        s["takes"].append({"path": paths[0], "quality": "edit", "resolution": resolution,
                           "interaction_id": extra.get("interaction_id"), "ts": _now(),
                           "est_cost_usd": est, "edit": prompt})
        s["selected_take"] = len(s["takes"]) - 1
        project.add_spend(p, core.billed(est))
        project.save(p)
        board.write(p)
        return (f"Shot {shot} edited: take {len(s['takes'])} is now selected ({pricing.fmt_usd(est)}).\n{paths[0]}\n"
                "Use flow_review to check it; flow_shot_update(select_take=...) switches back.")
    return core._video_result(paths, extra, est)


@core.tool()
async def flow_generate_music(
    prompt: str,
    kind: str = "clip",
    instrumental: bool = True,
    attach: bool = True,
    project_name: Optional[str] = None,
) -> str:
    """
    Generate music with Lyria: a 30-second clip (about $0.04) or a full song (about $0.08).

    Describe genre, mood, tempo and instruments. In a project the track becomes the film's
    background music (looped and faded out by flow_assemble).

    Args:
        prompt: e.g. 'warm lo-fi piano with soft vinyl crackle, 80 bpm, hopeful'.
        kind: 'clip' (30 s) or 'song' (a couple of minutes, can include lyrics).
        instrumental: Ask for no vocals (default true; best for background music).
        attach: Store it as the active project's music.
        project_name: Project to use (default: active project, if any).
    """
    if kind not in ("clip", "song"):
        raise ValueError("kind must be 'clip' or 'song'.")
    model_id = config.music_model(kind)
    text = prompt.strip()
    if instrumental and "instrumental" not in text.lower():
        text += " Instrumental only, no vocals."
    p = _optional_project(project_name, attach)
    out = project.sub(p, "audio") if p else config.output_dir()
    est = pricing.music_cost(model_id)

    async def work() -> tuple[list[str], dict]:
        client = core.get_client()
        inter = await client.aio.interactions.create(model=model_id, input=text)
        items = core._media_items(inter, "audio")
        if not items:
            raise core._no_media_error(inter, "audio")
        path = ledger.new_path(out, "music", prompt, core._ext(items[-1], "mp3"))
        path.write_bytes(await core._media_bytes(client, items[-1]))
        return [str(path)], {"lyrics": (getattr(inter, "output_text", "") or "")[:1500]}

    paths, extra = await core._tracked(
        tool="flow_generate_music", kind="audio", count=1, model=model_id, prompt=prompt,
        params={"kind": kind, "instrumental": instrumental, "project": p["name"] if p else None},
        est_cost=est, work=work,
    )
    lines = [f"Music saved ({model_id}, {pricing.fmt_usd(est)}):", paths[0]]
    if p:
        p = project.load(p["name"])
        p.setdefault("audio", {})["music"] = {"path": paths[0], "prompt": prompt}
        project.add_spend(p, core.billed(est))
        project.save(p)
        board.write(p)
        lines.append(f"Attached to project '{p['name']}' as background music.")
    if extra.get("lyrics") and not instrumental:
        lines.append("Lyrics / structure:\n" + extra["lyrics"])
    lines.append("Generated audio carries an inaudible SynthID watermark.")
    return "\n".join(lines) + core.demo_note()


@core.tool()
async def flow_generate_narration(
    text: str,
    voice: str = "Kore",
    style: Optional[str] = None,
    attach: bool = True,
    project_name: Optional[str] = None,
) -> str:
    """
    Generate a voice-over with Gemini TTS (130+ languages, including Korean; very cheap).

    Inline tags such as <short pause>, <laugh> or <whisper> are supported.
    In a project the narration is laid over the film from the start by flow_assemble.

    Args:
        text: The words to speak.
        voice: Prebuilt voice, e.g. Kore (firm), Puck (upbeat), Charon (informative),
               Aoede (breezy), Sulafat (warm), Achird (friendly), Gacrux (mature).
        style: Delivery, e.g. 'calm documentary narrator' or 'excited, fast'.
        attach: Store it as the active project's narration.
        project_name: Project to use (default: active project, if any).
    """
    spoken = text.strip()
    if not spoken:
        raise ValueError("text is empty.")
    model_id = config.tts_model()
    content: dict = {"type": "text", "text": spoken}
    if style:
        content["annotations"] = [{"type": "speech_metadata", "style": style}]
    p = _optional_project(project_name, attach)
    out = project.sub(p, "audio") if p else config.output_dir()
    est = pricing.speech_cost(model_id, len(spoken) / 14)

    async def work() -> tuple[list[str], dict]:
        client = core.get_client()
        inter = await client.aio.interactions.create(
            model=model_id,
            input=[{"type": "user_input", "content": [content]}],
            response_format={"type": "audio"},
            generation_config={"speech_config": [{"voice": voice}]},
        )
        items = core._media_items(inter, "audio")
        if not items:
            raise core._no_media_error(inter, "audio")
        data = await core._media_bytes(client, items[-1])
        path = ledger.new_path(out, "narration", spoken, core._ext(items[-1], "wav"))
        path.write_bytes(data)
        return [str(path)], {"audio_seconds": round(media.wav_seconds(data), 1)}

    paths, extra = await core._tracked(
        tool="flow_generate_narration", kind="audio", count=1, model=model_id, prompt=spoken[:500],
        params={"voice": voice, "style": style, "project": p["name"] if p else None},
        est_cost=est, work=work,
    )
    secs = extra.get("audio_seconds") or 0
    lines = [f"Narration saved ({model_id}, voice {voice}, about {secs}s, {pricing.fmt_usd(est)}):", paths[0]]
    if p:
        p = project.load(p["name"])
        p.setdefault("audio", {})["narration"] = {"path": paths[0], "prompt": spoken[:300], "seconds": secs}
        project.add_spend(p, core.billed(est))
        project.save(p)
        board.write(p)
        planned = sum(s["duration"] for s in p["shots"])
        lines.append(f"Attached to project '{p['name']}'. Planned film length: {planned}s.")
        if planned and secs > planned:
            lines.append("WARNING: the narration is longer than the film and will be cut off. Shorten the text or lengthen shots.")
    return "\n".join(lines)


@core.tool()
async def flow_assemble(
    shots: Optional[list[int]] = None,
    with_music: bool = True,
    with_narration: bool = True,
    music_volume: float = 0.25,
    clip_volume: float = 1.0,
    project_name: Optional[str] = None,
) -> Any:
    """
    Join the selected take of each shot into one film (local ffmpeg, no API cost).

    Applies per-shot trims, keeps each clip's own audio, and mixes in the project's music
    (looped, faded out) and narration when present.

    Args:
        shots: Shot numbers in playback order. Default: all shots in storyboard order.
        with_music: Use the project's music if there is one.
        with_narration: Use the project's narration if there is one.
        music_volume: 0-1, default 0.25 so it sits under dialogue.
        clip_volume: Volume of the clips' own audio (0 mutes it).
        project_name: Project to use (default: active project).
    """
    if not media.ffmpeg_exe():
        raise RuntimeError("ffmpeg not found. Install ffmpeg or set FLOW_FFMPEG to its full path.")
    p = project.load(project_name)
    name = p["name"]
    ids = _ids(p, shots)
    if not ids:
        raise ValueError("No shots yet. Call flow_storyboard_plan first.")
    clips, missing = [], []
    for i in ids:
        s = project.get_shot(p, i)
        take = project.selected_take(s)
        if not take or not Path(take["path"]).is_file():
            missing.append(i)
        else:
            clips.append({"path": take["path"], "start": s["trim"][0], "end": s["trim"][1]})
    if missing:
        raise ValueError(f"Shot(s) {missing} have no rendered take. Render them or pass shots=[...] without them.")
    audio = p.get("audio") or {}
    music = audio.get("music", {}).get("path") if with_music else None
    narration = audio.get("narration", {}).get("path") if with_narration else None
    music = music if music and Path(music).is_file() else None
    narration = narration if narration and Path(narration).is_file() else None

    renders = project.sub(p, "renders")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    final = renders / f"{stamp}_{ledger.slug(p['title'])}.mp4"
    if music or narration or clip_volume != 1.0:
        cut = renders / f"{stamp}_{ledger.slug(p['title'])}_clips-only.mp4"
        await media.concat(clips, cut)
        if music or narration:
            await media.mix(cut, final, music=music, narration=narration,
                            music_volume=max(0.0, min(1.0, music_volume)), clip_volume=max(0.0, clip_volume))
        else:
            await media.run(["-y", "-i", str(cut), "-c:v", "copy", "-af", f"volume={max(0.0, clip_volume):.3f}",
                             "-c:a", "aac", "-movflags", "+faststart", str(final)])
    else:
        await media.concat(clips, final)
    info = await media.probe(final)

    p = project.load(name)
    p.setdefault("films", []).append({"path": str(final), "duration": info["duration"], "shots": ids,
                                      "music": bool(music), "narration": bool(narration), "ts": _now()})
    project.save(p)
    path = board.write(p)
    lines = [
        f"Film assembled: {len(clips)} shot(s), {info['duration']}s, {info['width']}x{info['height']}"
        + (", with music" if music else "") + (", with narration" if narration else "") + ".",
        str(final),
        f"Board: {path}",
    ]
    narr_secs = float(audio.get("narration", {}).get("seconds") or 0) if narration else 0
    if narr_secs and narr_secs > info["duration"]:
        lines.append(f"WARNING: narration ({narr_secs}s) is longer than the film ({info['duration']}s) and was cut off.")
    lines.append("Frames below are evenly spaced through the film. Check continuity before calling it done.")
    previews: list[bytes] = []
    if config.inline_preview():
        try:
            sheet, _ = await media.video_sheet(final, frames=min(9, max(3, len(clips) * 2)))
            previews = [sheet] if sheet else []
        except Exception:
            previews = []
    return core._reply("\n".join(lines), previews)


# ── Review + board ────────────────────────────────────────────────────────────


@core.tool()
async def flow_review(path: str, frames: int = 6) -> Any:
    """
    Look at a generated file: returns the image, or evenly spaced frames of a video.

    Use this to check a result with your own eyes before telling the user it is good:
    faces and hands, text spelling, continuity between frames, whether the prompt was followed.

    Args:
        path: Image or video file.
        frames: Number of video frames to sample (1-12, default 6).
    """
    target = Path(path).expanduser()
    if not target.is_file():
        raise ValueError(f"File not found: {path}")
    if target.suffix.lower() in IMAGE_EXTS:
        from PIL import Image as PILImage

        with PILImage.open(target) as im:
            size = f"{im.width}x{im.height}"
        thumb = media.thumbnail_bytes(target, 1024)
        return [f"Image {target.name}: {size}, {target.stat().st_size // 1024} KB.", core._Image(data=thumb, format="jpeg")]
    if not media.ffmpeg_exe():
        raise RuntimeError("ffmpeg not found; it is needed to sample video frames. Set FLOW_FFMPEG.")
    sheet, info = await media.video_sheet(target, frames=max(1, min(12, frames)))
    text = (f"Video {target.name}: {info['duration']}s, {info['width']}x{info['height']}, "
            f"audio {'yes' if info['has_audio'] else 'no'}, {target.stat().st_size // 1024} KB. "
            "Frames are labelled with their timestamps (sound cannot be reviewed this way).")
    if not sheet:
        return text + " Could not extract frames."
    return [text, core._Image(data=sheet, format="jpeg")]


@core.tool()
async def flow_board(open_in_browser: bool = False, project_name: Optional[str] = None) -> str:
    """
    Write the project's HTML board (ingredients, storyboard with players, audio, latest film).

    Args:
        open_in_browser: Also open it in the default browser on this computer.
        project_name: Project to use (default: active project).
    """
    p = project.load(project_name)
    _sync_jobs(p)
    path = board.write(p)
    opened = ""
    if open_in_browser:
        try:
            webbrowser.open(path.as_uri())
            opened = " Opened in the browser."
        except Exception as exc:
            opened = f" Could not open the browser: {exc}"
    return f"Board written: {path}{opened}\n{path.as_uri()}"


# ── Prompts (ready-made workflows) ────────────────────────────────────────────


@mcp.prompt()
def short_film(idea: str, seconds: str = "20", orientation: str = "16:9") -> str:
    """Plan and produce a short multi-shot film with consistent characters."""
    return (
        f"Make a short film of about {seconds} seconds ({orientation}) from this idea: {idea}\n\n"
        "Work in this order and show me each result before the next paid step:\n"
        "1. flow_project with a short name, the orientation and one style line.\n"
        "2. flow_ingredient_save for each recurring character, object or location (generate=true if I gave no images).\n"
        "3. flow_storyboard_plan: 3-6 shots, each with prompt, action, camera, sound; use @names.\n"
        "4. flow_storyboard_keyframes. Look at the sheet yourself and tell me honestly what is weak.\n"
        "5. After I approve, flow_storyboard_render quality='draft'. Review with flow_review.\n"
        "6. Offer music (flow_generate_music) and narration (flow_generate_narration).\n"
        "7. flow_assemble, then flow_board. Report the total estimated cost."
    )


@mcp.prompt()
def product_ad(product: str, platform: str = "shorts") -> str:
    """A 10-15 second product ad with a consistent product look."""
    return (
        f"Create a 10-15 second ad for: {product}. Target platform: {platform}.\n"
        "Save the product as an 'object' ingredient (ask me for a photo path; otherwise generate=true). "
        "Plan 3 shots: hook (macro or push-in), benefit in use, final hero shot with space for a caption. "
        "Generate keyframes first and show them. Use draft renders until I approve, then standard. "
        "Add a short upbeat instrumental music clip and assemble."
    )


@mcp.prompt()
def social_image_set(topic: str, style: str = "flat-illustration") -> str:
    """One idea as a YouTube thumbnail, a Pinterest pin and a Shorts cover."""
    return (
        f"Make a matching image set about: {topic}. Style preset: {style}.\n"
        "Use flow_generate_image three times with preset='youtube-thumbnail', 'pinterest-pin' and 'shorts'. "
        "Keep the same subject, palette and headline text in all three. Look at each preview and redo any "
        "with misspelled text. Finish with flow_usage_today."
    )
