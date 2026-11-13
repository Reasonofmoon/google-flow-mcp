"""Google Flow MCP server (Reasonofmoon fork): core generation tools.

Images: Nano Banana models through the Gemini Interactions API.
Video:  Gemini Omni Flash (Veo 3.1 Preview was shut down on 2026-10-22).
Project, storyboard, audio and review tools live in studio.py.
"""

from __future__ import annotations

import asyncio
import base64
import mimetypes
import os
import re
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional, Sequence

from google import genai

try:  # mcp >= 2
    from mcp.server.mcpserver import Image as _Image
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server
    from mcp.server.fastmcp import Image as _Image

from . import __version__, config, ledger, media, presets, pricing, project

FILE_POLL_INTERVAL = 5     # seconds between Files API status checks
FILE_POLL_TIMEOUT = 600    # 10 minutes
VIDEO_ASPECTS = ("16:9", "9:16")
VIDEO_RESOLUTIONS = ("360p", "720p", "1080p", "4k")

INSTRUCTIONS = (
    f"google-flow-mcp {__version__}: Flow-style creative studio on the Gemini API "
    "(not the Flow web app; billing is the user's Gemini API key).\n"
    "QUICK JOBS: flow_generate_image / flow_edit_image / flow_generate_video. Image models: "
    "'fast' (Nano Banana 2.1, default), 'pro' (best text and layouts), 'lite'. Video: Gemini Omni "
    "Flash, 3-15 s with native audio, 16:9 or 9:16. Use preset=, style=, camera= "
    "(see flow_list_presets).\n"
    "FILMS (several shots, consistent characters): 1) flow_project 2) flow_ingredient_save for each "
    "character/object/location, then write @name in prompts 3) flow_storyboard_plan "
    "4) flow_storyboard_keyframes and LOOK at the returned sheet; fix weak shots with "
    "flow_shot_update before paying for video 5) flow_storyboard_render quality='draft' (360p, "
    "about a third of the price), review, then 'standard' for the shots that work "
    "6) optional flow_generate_music / flow_generate_narration 7) flow_assemble 8) flow_board.\n"
    "LOOK BEFORE YOU SPEND: tools return small previews; use flow_review on any image or video to "
    "see frames and judge it honestly before going on.\n"
    "COST: image, video and music models need a paid key. Calls above the cost threshold return "
    "an estimate first: show it to the user and only repeat with confirm_cost=true after they "
    "agree. Daily limits and a daily budget apply (flow_usage_today). Never claim a file was "
    "made unless the tool returned its path."
)

mcp = _Server("google-flow-mcp", instructions=INSTRUCTIONS)

# ── Client ────────────────────────────────────────────────────────────────────

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key or api_key.startswith("YOUR_"):
        raise EnvironmentError(
            "GOOGLE_API_KEY is not set. Put a paid Gemini API key in the env block of "
            "claude_desktop_config.json (get one at https://aistudio.google.com/apikey)."
        )
    return genai.Client(api_key=api_key)


def get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = _get_client()
    return _client


# ── Helpers ───────────────────────────────────────────────────────────────────


def _mime(path: str) -> str:
    mime, _ = mimetypes.guess_type(path)
    return mime or "image/png"


def _image_part(path: str) -> dict:
    data = Path(path).expanduser().read_bytes()
    return {"type": "image", "data": base64.b64encode(data).decode("ascii"), "mime_type": _mime(path)}


def _decode(data) -> bytes:
    if isinstance(data, (bytes, bytearray)):
        return bytes(data)
    return base64.b64decode(data)


_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "video/mp4": "mp4",
        "audio/mpeg": "mp3", "audio/mp3": "mp3", "audio/wav": "wav", "audio/x-wav": "wav"}


def _ext(item, default: str) -> str:
    mime = getattr(item, "mime_type", None)
    mime = getattr(mime, "value", mime)
    return _EXT.get(str(mime or "").lower(), default)


def _media_items(interaction, kind: str) -> list:
    """All `kind` ('image' / 'video') outputs from model_output steps."""
    items = []
    for step in getattr(interaction, "steps", None) or []:
        if getattr(step, "type", None) != "model_output":
            continue
        for item in getattr(step, "content", None) or []:
            if getattr(item, "type", None) == kind:
                items.append(item)
    if not items:
        single = getattr(interaction, f"output_{kind}", None)
        if single is not None:
            items.append(single)
    return items


def _previews(paths: Sequence[str]) -> list[bytes]:
    """One thumbnail, or a contact sheet for several images. Empty if nothing opens."""
    if not config.inline_preview():
        return []
    valid = [p for p in paths if media.safe_thumbnail(p, 64) is not None]
    if not valid:
        return []
    if len(valid) == 1:
        return [media.thumbnail_bytes(valid[0])]
    return [media.contact_sheet([(str(i + 1), p) for i, p in enumerate(valid)], cols=2)]


def _reply(text: str, previews: Sequence[bytes] = ()) -> Any:
    """Text plus inline JPEG previews the assistant can look at."""
    if not previews or not config.inline_preview():
        return text
    return [text, *(_Image(data=b, format="jpeg") for b in previews)]


def _active_project() -> Optional[dict]:
    try:
        return project.load()
    except ValueError:
        return None


def _state(obj) -> str:
    state = getattr(obj, "state", None)
    return str(getattr(state, "name", state) or "").upper()


async def _wait_file(client: genai.Client, name: str):
    deadline = time.monotonic() + FILE_POLL_TIMEOUT
    f = await client.aio.files.get(name=name)
    while "ACTIVE" not in _state(f):
        if "FAILED" in _state(f):
            raise RuntimeError(f"File processing failed: {name}")
        if time.monotonic() > deadline:
            raise TimeoutError(f"File {name} was not ready after {FILE_POLL_TIMEOUT // 60} minutes.")
        await asyncio.sleep(FILE_POLL_INTERVAL)
        f = await client.aio.files.get(name=name)
    return f


async def _media_bytes(client: genai.Client, item) -> bytes:
    data = getattr(item, "data", None)
    if data:
        return _decode(data)
    uri = getattr(item, "uri", None)
    if not uri:
        raise RuntimeError("The model returned media without data or uri.")
    m = re.search(r"files/([^:/?]+)", uri)
    if m:
        await _wait_file(client, f"files/{m.group(1)}")
    return await client.aio.files.download(file=uri)


async def _upload(client: genai.Client, path: str):
    f = await client.aio.files.upload(file=str(Path(path).expanduser()))
    if "ACTIVE" not in _state(f):
        f = await _wait_file(client, f.name)
    return f


def _no_media_error(interaction, kind: str) -> RuntimeError:
    said = (getattr(interaction, "output_text", "") or "").strip()
    status = getattr(interaction, "status", "")
    return RuntimeError(
        f"No {kind} returned (status={status}). "
        + (f"Model said: {said[:500]}" if said else "The request may have been blocked by safety filters.")
    )


async def _tracked(
    *, tool: str, kind: str, count: int, model: str, prompt: str, params: dict,
    est_cost: float | None, work: Callable[[], Awaitable[tuple[list[str], dict]]],
) -> tuple[list[str], dict]:
    """Check daily limits, run the work, and append a line to the JSONL log."""
    ledger.check_limits(kind, count, est_cost)
    base = {"tool": tool, "kind": kind, "model": model, "prompt": prompt, "params": params,
            "count": count, "est_cost_usd": est_cost}
    t0 = time.monotonic()
    try:
        outputs, extra = await work()
    except Exception as exc:
        ledger.record({**base, "count": 0, "est_cost_usd": 0, "status": "error",
                       "error": f"{type(exc).__name__}: {exc}"[:500],
                       "seconds": round(time.monotonic() - t0, 1)})
        raise
    ledger.record({**base, "status": "ok", "outputs": outputs, **extra,
                   "seconds": round(time.monotonic() - t0, 1)})
    return outputs, extra


async def _images(
    *, model: str, input_, n: int, aspect_ratio: Optional[str], image_size: Optional[str],
    out: Path, kind: str, prompt: str,
) -> tuple[list[str], dict]:
    client = get_client()
    response_format: dict = {"type": "image"}
    if aspect_ratio:
        response_format["aspect_ratio"] = aspect_ratio
    if image_size:
        response_format["image_size"] = image_size

    async def one(i: int) -> tuple[str, Optional[str]]:
        inter = await client.aio.interactions.create(model=model, input=input_, response_format=response_format)
        items = _media_items(inter, "image")
        if not items:
            raise _no_media_error(inter, "image")
        item = items[-1]
        path = ledger.new_path(out, kind, prompt, _ext(item, "png"), i if n > 1 else None)
        path.write_bytes(await _media_bytes(client, item))
        return str(path), getattr(inter, "id", None)

    results = await asyncio.gather(*(one(i) for i in range(n)))
    return [p for p, _ in results], {"interaction_ids": [i for _, i in results if i]}


def _with_negative(prompt: str, negative: Optional[str]) -> str:
    return f"{prompt}\n\nAvoid: {negative}" if negative else prompt


def _video_format(duration: int, aspect: str, resolution: str) -> dict:
    fmt = {"type": "video", "aspect_ratio": aspect, "duration": f"{duration}s", "resolution": resolution}
    if resolution in ("1080p", "4k"):
        fmt["delivery"] = "uri"  # inline data is limited to ~4 MB
    return fmt


def _check_video_args(aspect: str, resolution: str) -> None:
    if aspect not in VIDEO_ASPECTS:
        raise ValueError(f"Video aspect_ratio must be one of {VIDEO_ASPECTS}; got {aspect}.")
    if resolution not in VIDEO_RESOLUTIONS:
        raise ValueError(f"resolution must be one of {VIDEO_RESOLUTIONS}; got {resolution}.")


def _cost_gate(est: float | None, what: str, confirm_cost: bool) -> Optional[str]:
    threshold = config.video_confirm_usd()
    if confirm_cost or not threshold or est is None or est <= threshold:
        return None
    return (
        f"NOT GENERATED YET. Estimated cost for {what}: {pricing.fmt_usd(est)} "
        f"(prices checked {pricing.PRICES_CHECKED}), above FLOW_VIDEO_CONFIRM_USD=${threshold:.2f}. "
        "Show this estimate to the user. If they agree, call the same tool again with confirm_cost=true."
    )


async def _video(
    *, model: str, input_, response_format: dict, out: Path, kind: str, prompt: str,
    previous_interaction_id: Optional[str] = None,
) -> tuple[list[str], dict]:
    client = get_client()
    kwargs: dict = {"model": model, "input": input_, "response_format": response_format}
    if previous_interaction_id:
        kwargs["previous_interaction_id"] = previous_interaction_id
    inter = await client.aio.interactions.create(**kwargs)
    items = _media_items(inter, "video")
    if not items:
        raise _no_media_error(inter, "video")
    path = ledger.new_path(out, kind, prompt, "mp4")
    path.write_bytes(await _media_bytes(client, items[-1]))
    return [str(path)], {"interaction_id": getattr(inter, "id", None)}


def _video_result(paths: list[str], extra: dict, est: float | None) -> str:
    lines = ["Saved video:", *paths, f"Estimated cost: {pricing.fmt_usd(est)}"]
    if extra.get("interaction_id"):
        lines.append(
            f"interaction_id: {extra['interaction_id']} "
            "(pass as previous_interaction_id to flow_extend_video to continue or edit this clip)"
        )
    lines.append("Note: all generated videos carry an invisible SynthID watermark.")
    return "\n".join(lines)


# ── Tool 1: Text → Image ─────────────────────────────────────────────────────


@mcp.tool(structured_output=False)
async def flow_generate_image(
    prompt: str,
    model: Optional[str] = None,
    number_of_images: int = 1,
    aspect_ratio: Optional[str] = None,
    image_size: Optional[str] = None,
    preset: Optional[str] = None,
    style: Optional[str] = None,
    negative_prompt: Optional[str] = None,
    output_dir: Optional[str] = None,
) -> str:
    """
    Generate 1-4 images from a text prompt with a Nano Banana model.

    Args:
        prompt: Description of the image. Text inside quotes is rendered as on-image text.
        model: 'fast' (Nano Banana 2.1, default), 'pro' (Nano Banana Pro), 'lite', or a full model id.
        number_of_images: 1-4 (each image is a separate request and is billed separately).
        aspect_ratio: e.g. '1:1', '2:3', '3:4', '4:5', '9:16', '16:9', '21:9'. Overrides preset.
        image_size: '1K', '2K' or '4K'. Overrides preset. Lite supports 1K only.
        preset: Format preset, e.g. 'youtube-thumbnail', 'shorts', 'pinterest-pin', 'worksheet'.
        style: Style preset, e.g. 'photo', 'watercolor', 'kids-book', 'infographic'.
        negative_prompt: Things to avoid.
        output_dir: Override the output folder.
    """
    fmt = presets.resolve_format(preset)
    model_id = config.image_model(model)
    n = max(1, min(4, number_of_images))
    ar = aspect_ratio or fmt.get("aspect_ratio")
    size = image_size or fmt.get("image_size")
    full, refs, used = project.expand(_active_project(), presets.apply_style(prompt, style),
                                      max_images=14, per_ingredient=3)
    full = _with_negative(full, negative_prompt)
    input_ = full if not refs else [{"type": "text", "text": full}, *(_image_part(r) for r in refs)]
    out = config.output_dir(output_dir)
    est = pricing.image_cost(model_id, size or "1K", n)

    paths, _ = await _tracked(
        tool="flow_generate_image", kind="image", count=n, model=model_id, prompt=prompt,
        params={"aspect_ratio": ar, "image_size": size, "preset": preset, "style": style,
                "ingredients": used},
        est_cost=est,
        work=lambda: _images(model=model_id, input_=input_, n=n, aspect_ratio=ar, image_size=size,
                             out=out, kind="image", prompt=prompt),
    )
    note = f" using ingredients {', '.join('@' + u for u in used)}" if used else ""
    return _reply(
        f"Generated {len(paths)} image(s) with {model_id}{note} ({pricing.fmt_usd(est)}):\n" + "\n".join(paths),
        _previews(paths),
    )


# ── Tool 2: Edit Image ────────────────────────────────────────────────────────

_EDIT_HINTS = {
    "inpaint_insertion": "Add the following to the image, keep everything else unchanged: ",
    "inpaint_removal": "Remove the following from the image, fill the area naturally, keep everything else unchanged: ",
    "outpaint": "Extend the canvas beyond its current borders and continue the scene naturally: ",
    "bgswap": "Keep the main subject exactly as it is and replace only the background with: ",
    "free": "",
}


@mcp.tool(structured_output=False)
async def flow_edit_image(
    image_path: str,
    prompt: str,
    edit_mode: str = "free",
    model: Optional[str] = None,
    aspect_ratio: Optional[str] = None,
    image_size: Optional[str] = None,
    output_dir: Optional[str] = None,
    mask_mode: Optional[str] = None,
) -> str:
    """
    Edit an existing image with a natural-language instruction (no mask needed).

    Args:
        image_path: Path to the source image.
        prompt: What to change.
        edit_mode: 'free' (default, just follow the prompt), 'inpaint_insertion' (add),
                   'inpaint_removal' (remove), 'outpaint' (extend canvas), 'bgswap' (new background).
        model: 'fast' (default), 'pro', 'lite', or a full model id.
        aspect_ratio: Output aspect ratio. Defaults to the input image's shape.
        image_size: '1K', '2K' or '4K'.
        output_dir: Override the output folder.
        mask_mode: Ignored. Kept for compatibility with 0.1.0 (Nano Banana edits need no mask).
    """
    if edit_mode not in _EDIT_HINTS:
        raise ValueError(f"edit_mode must be one of {sorted(_EDIT_HINTS)}; got {edit_mode}.")
    model_id = config.image_model(model)
    out = config.output_dir(output_dir)
    input_ = [{"type": "text", "text": _EDIT_HINTS[edit_mode] + prompt}, _image_part(image_path)]
    est = pricing.image_cost(model_id, image_size or "1K", 1)

    paths, _ = await _tracked(
        tool="flow_edit_image", kind="image", count=1, model=model_id, prompt=prompt,
        params={"image_path": image_path, "edit_mode": edit_mode, "aspect_ratio": aspect_ratio,
                "image_size": image_size},
        est_cost=est,
        work=lambda: _images(model=model_id, input_=input_, n=1, aspect_ratio=aspect_ratio,
                             image_size=image_size, out=out, kind="edit", prompt=prompt),
    )
    return _reply(f"Edited image saved to ({pricing.fmt_usd(est)}):\n{paths[0]}", _previews(paths))


# ── Tool 3: Generate with Reference Images ────────────────────────────────────


@mcp.tool(structured_output=False)
async def flow_generate_image_with_references(
    prompt: str,
    reference_image_paths: list[str],
    model: Optional[str] = None,
    aspect_ratio: Optional[str] = None,
    image_size: Optional[str] = None,
    preset: Optional[str] = None,
    style: Optional[str] = None,
    number_of_images: int = 1,
    output_dir: Optional[str] = None,
) -> str:
    """
    Generate images guided by up to 14 reference images (characters, objects, style).

    Nano Banana 2.1: up to 10 object + 4 character images.
    Nano Banana Pro: up to 6 object + 5 character + 3 style images.

    Args:
        prompt: What to create and how to use the references.
        reference_image_paths: 1-14 image paths.
        model: 'fast' (default), 'pro', 'lite', or a full model id.
        aspect_ratio / image_size / preset / style: same as flow_generate_image.
        number_of_images: 1-4.
        output_dir: Override the output folder.
    """
    if not reference_image_paths:
        raise ValueError("At least one reference image path is required.")
    if len(reference_image_paths) > 14:
        raise ValueError(f"Maximum 14 reference images allowed; got {len(reference_image_paths)}.")
    fmt = presets.resolve_format(preset)
    model_id = config.image_model(model)
    n = max(1, min(4, number_of_images))
    ar = aspect_ratio or fmt.get("aspect_ratio")
    size = image_size or fmt.get("image_size")
    out = config.output_dir(output_dir)
    text = presets.apply_style(prompt, style)
    input_ = [{"type": "text", "text": text}, *(_image_part(p) for p in reference_image_paths)]
    est = pricing.image_cost(model_id, size or "1K", n)

    paths, _ = await _tracked(
        tool="flow_generate_image_with_references", kind="image", count=n, model=model_id,
        prompt=prompt,
        params={"references": reference_image_paths, "aspect_ratio": ar, "image_size": size,
                "preset": preset, "style": style},
        est_cost=est,
        work=lambda: _images(model=model_id, input_=input_, n=n, aspect_ratio=ar, image_size=size,
                             out=out, kind="ref", prompt=prompt),
    )
    return _reply(
        f"Generated {len(paths)} image(s) using {len(reference_image_paths)} reference(s) "
        f"with {model_id} ({pricing.fmt_usd(est)}):\n" + "\n".join(paths),
        _previews(paths),
    )


# ── Tool 4: Text → Video ─────────────────────────────────────────────────────


@mcp.tool(structured_output=False)
async def flow_generate_video(
    prompt: str,
    duration_seconds: int = 8,
    aspect_ratio: Optional[str] = None,
    resolution: str = "720p",
    preset: Optional[str] = None,
    camera: Optional[str] = None,
    negative_prompt: Optional[str] = None,
    anchor_frame_path: Optional[str] = None,
    last_frame_path: Optional[str] = None,
    reference_image_paths: Optional[list[str]] = None,
    confirm_cost: bool = False,
    output_dir: Optional[str] = None,
    enhance_prompt: bool = True,
) -> str:
    """
    Generate a video with native audio using Gemini Omni Flash.

    Args:
        prompt: Scene, camera movement, lighting, mood, sound. Say "single continuous shot"
                if you do not want cuts.
        duration_seconds: 3-15 (3-10 when last_frame_path is given).
        aspect_ratio: '16:9' or '9:16'. Overrides preset.
        resolution: '360p', '720p' (default), '1080p' or '4k' (1080p/4k are upscaled).
        preset: e.g. 'shorts' (9:16) or 'youtube-thumbnail' (16:9).
        camera: Camera move preset ('push-in', 'orbit', 'drone', 'handheld', ... see
                flow_list_presets) or your own description.
        negative_prompt: Things to avoid (e.g. "no dialogue, no text").
        anchor_frame_path: Image to start from (image-to-video).
        last_frame_path: Image to end on (needs anchor_frame_path; interpolation).
        reference_image_paths: Up to 6 images of characters/objects to keep consistent.
        confirm_cost: Set true only after the user accepted the cost estimate.
        output_dir: Override the output folder.
        enhance_prompt: Ignored. Kept for compatibility with 0.1.0.
    """
    fmt = presets.resolve_format(preset)
    aspect = aspect_ratio or fmt.get("video_aspect_ratio") or "16:9"
    _check_video_args(aspect, resolution)
    if last_frame_path and not anchor_frame_path:
        raise ValueError("last_frame_path needs anchor_frame_path as the first frame.")
    max_len = 10 if last_frame_path else 15
    duration = max(3, min(max_len, duration_seconds))
    refs = reference_image_paths or []
    if len(refs) > 6:
        raise ValueError(f"Maximum 6 reference images for video; got {len(refs)}.")

    model_id = config.video_model()
    est = pricing.video_cost(model_id, duration, resolution)
    gate = _cost_gate(est, f"{duration}s {resolution} video with {model_id}", confirm_cost)
    if gate:
        return gate

    frames = [p for p in (anchor_frame_path, last_frame_path) if p]
    text = prompt + (f"\nCamera: {presets.camera_phrase(camera)}." if camera else "")
    text, tagged, used = project.expand(_active_project(), text, offset=len(frames) + len(refs),
                                        max_images=max(0, 6 - len(frames) - len(refs)), per_ingredient=2)
    text = _with_negative(text, negative_prompt)
    images = frames + refs + tagged
    input_ = text if not images else [*(_image_part(p) for p in images), {"type": "text", "text": text}]
    out = config.output_dir(output_dir)

    paths, extra = await _tracked(
        tool="flow_generate_video", kind="video", count=1, model=model_id, prompt=prompt,
        params={"duration": duration, "aspect_ratio": aspect, "resolution": resolution,
                "camera": camera, "anchor": anchor_frame_path, "last_frame": last_frame_path,
                "references": refs, "ingredients": used},
        est_cost=est,
        work=lambda: _video(model=model_id, input_=input_,
                            response_format=_video_format(duration, aspect, resolution),
                            out=out, kind="video", prompt=prompt),
    )
    return _video_result(paths, extra, est)


# ── Tool 5: Extend / edit a video ─────────────────────────────────────────────


@mcp.tool(structured_output=False)
async def flow_extend_video(
    prompt: str,
    video_path: Optional[str] = None,
    previous_interaction_id: Optional[str] = None,
    duration_seconds: int = 8,
    resolution: str = "720p",
    reference_image_paths: Optional[list[str]] = None,
    confirm_cost: bool = False,
    output_dir: Optional[str] = None,
    aspect_ratio: Optional[str] = None,
) -> str:
    """
    Continue or edit a video with Gemini Omni Flash.

    Best: pass previous_interaction_id from an earlier video result (keeps full context,
    supports new dialogue). Otherwise pass video_path to upload a clip of 15 s or less.
    Extension adds 3-10 s per turn, up to 30 s total. Prompts like "Make the sky purple"
    edit the clip instead of extending it.

    Args:
        prompt: How the scene continues, or what to change.
        video_path: Local MP4 to extend (uploaded through the Files API).
        previous_interaction_id: interaction_id printed by an earlier video tool.
        duration_seconds: Length of the new part, 3-10.
        resolution: '360p', '720p', '1080p' or '4k'.
        reference_image_paths: Images of new characters/objects to bring in.
        confirm_cost: Set true only after the user accepted the cost estimate.
        output_dir: Override the output folder.
        aspect_ratio: Ignored (the source clip decides). Kept for compatibility with 0.1.0.
    """
    if not video_path and not previous_interaction_id:
        raise ValueError("Provide previous_interaction_id (preferred) or video_path.")
    if resolution not in VIDEO_RESOLUTIONS:
        raise ValueError(f"resolution must be one of {VIDEO_RESOLUTIONS}; got {resolution}.")
    duration = max(3, min(10, duration_seconds))
    model_id = config.video_model()
    est = pricing.video_cost(model_id, duration, resolution)
    gate = _cost_gate(est, f"{duration}s {resolution} extension with {model_id}", confirm_cost)
    if gate:
        return gate
    out = config.output_dir(output_dir)
    refs = reference_image_paths or []

    async def work() -> tuple[list[str], dict]:
        response_format = {"type": "video", "duration": f"{duration}s", "resolution": resolution}
        if resolution in ("1080p", "4k"):
            response_format["delivery"] = "uri"
        if previous_interaction_id:
            input_ = prompt if not refs else [*(_image_part(p) for p in refs), {"type": "text", "text": prompt}]
            return await _video(model=model_id, input_=input_, response_format=response_format,
                                out=out, kind="extend", prompt=prompt,
                                previous_interaction_id=previous_interaction_id)
        uploaded = await _upload(get_client(), video_path)
        input_ = [{"type": "video", "uri": uploaded.uri}, *(_image_part(p) for p in refs),
                  {"type": "text", "text": prompt}]
        return await _video(model=model_id, input_=input_, response_format=response_format,
                            out=out, kind="extend", prompt=prompt)

    paths, extra = await _tracked(
        tool="flow_extend_video", kind="video", count=1, model=model_id, prompt=prompt,
        params={"video_path": video_path, "previous_interaction_id": previous_interaction_id,
                "duration": duration, "resolution": resolution, "references": refs},
        est_cost=est, work=work,
    )
    return _video_result(paths, extra, est)


# ── Tool 6: Image → Video Pipeline ───────────────────────────────────────────


@mcp.tool(structured_output=False)
async def flow_image_to_video(
    video_prompt: str,
    image_prompt: Optional[str] = None,
    image_path: Optional[str] = None,
    image_model: str = "pro",
    duration_seconds: int = 8,
    aspect_ratio: Optional[str] = None,
    resolution: str = "720p",
    preset: Optional[str] = None,
    style: Optional[str] = None,
    negative_prompt: Optional[str] = None,
    confirm_cost: bool = False,
    output_dir: Optional[str] = None,
) -> str:
    """
    Pipeline: make (or reuse) an anchor image, then animate it with Gemini Omni Flash.

    Args:
        video_prompt: How the scene should move.
        image_prompt: Prompt for a new anchor image (if image_path is not given).
        image_path: Existing image to animate.
        image_model: 'pro' (default here, best detail), 'fast' or 'lite'.
        duration_seconds: 3-15.
        aspect_ratio: '16:9' or '9:16'. Overrides preset.
        resolution: '360p', '720p', '1080p' or '4k'.
        preset: e.g. 'shorts' or 'youtube-thumbnail'.
        style: Style preset for the anchor image.
        negative_prompt: Things to avoid in both steps.
        confirm_cost: Set true only after the user accepted the cost estimate.
        output_dir: Override the output folder.
    """
    if not image_prompt and not image_path:
        raise ValueError("Provide either image_prompt or image_path.")
    fmt = presets.resolve_format(preset)
    aspect = aspect_ratio or fmt.get("video_aspect_ratio") or "16:9"
    _check_video_args(aspect, resolution)
    duration = max(3, min(15, duration_seconds))
    video_model_id = config.video_model()
    image_model_id = config.image_model(image_model)
    img_size = fmt.get("image_size") or "2K"
    v_est = pricing.video_cost(video_model_id, duration, resolution)
    i_est = 0.0 if image_path else pricing.image_cost(image_model_id, img_size, 1)
    total = None if v_est is None or i_est is None else round(v_est + i_est, 4)
    gate = _cost_gate(total, f"anchor image + {duration}s {resolution} video", confirm_cost)
    if gate:
        return gate

    out = config.output_dir(output_dir)
    lines: list[str] = []
    anchor = image_path
    if not anchor:
        full = _with_negative(presets.apply_style(image_prompt, style), negative_prompt)
        img_paths, _ = await _tracked(
            tool="flow_image_to_video:image", kind="image", count=1, model=image_model_id,
            prompt=image_prompt, params={"aspect_ratio": aspect, "image_size": img_size, "style": style},
            est_cost=i_est,
            work=lambda: _images(model=image_model_id, input_=full, n=1, aspect_ratio=aspect,
                                 image_size=img_size, out=out, kind="anchor", prompt=image_prompt),
        )
        anchor = img_paths[0]
        lines.append(f"Anchor image ({pricing.fmt_usd(i_est)}):\n{anchor}")

    text = _with_negative(video_prompt, negative_prompt)
    input_ = [_image_part(anchor), {"type": "text", "text": text}]
    paths, extra = await _tracked(
        tool="flow_image_to_video:video", kind="video", count=1, model=video_model_id,
        prompt=video_prompt,
        params={"anchor": anchor, "duration": duration, "aspect_ratio": aspect, "resolution": resolution},
        est_cost=v_est,
        work=lambda: _video(model=video_model_id, input_=input_,
                            response_format=_video_format(duration, aspect, resolution),
                            out=out, kind="video", prompt=video_prompt),
    )
    lines.append(_video_result(paths, extra, v_est))
    return "\n\n".join(lines)


# ── Tool 7-9: Presets, cost, usage ───────────────────────────────────────────


@mcp.tool(structured_output=False)
async def flow_list_presets() -> str:
    """List format presets, style presets, current models and limits."""
    lines = ["Format presets (preset=):"]
    for name, f in sorted(presets.all_formats().items()):
        video = f" | video {f['video_aspect_ratio']}" if f.get("video_aspect_ratio") else ""
        lines.append(f"- {name}: image {f.get('aspect_ratio')} {f.get('image_size', '')}{video} — {f.get('note', '')}")
    lines.append("\nStyle presets (style=):")
    for name, s in sorted(presets.all_styles().items()):
        lines.append(f"- {name}: {s}")
    lines.append("\nCamera moves (camera=, or write your own):")
    lines.append(", ".join(sorted(presets.CAMERA)))
    lines += [
        "\nVideo prompt tips: say 'single continuous shot' to avoid cuts; time events with "
        "'[0-4s] ... [4-8s] ...'; describe sound ('calm piano, no dialogue'); for edits keep it "
        "short and add 'Keep everything else the same'.",
        "\nModels:",
        f"- fast: {config.image_model('fast')}",
        f"- pro: {config.image_model('pro')}",
        f"- lite: {config.image_model('lite')}",
        f"- default image model: {config.image_model(None)}",
        f"- video: {config.video_model()}",
        f"- music: {config.music_model('clip')} (30 s clip), {config.music_model('song')} (full song)",
        f"- narration: {config.tts_model()}",
        f"- ffmpeg: {'found' if media.ffmpeg_exe() else 'NOT FOUND (needed for flow_assemble and video review)'}",
        "\nLimits: " + _limits_text(),
    ]
    return "\n".join(lines)


@mcp.tool(structured_output=False)
async def flow_estimate_cost(
    kind: str = "video",
    model: Optional[str] = None,
    count: int = 1,
    image_size: str = "1K",
    duration_seconds: int = 8,
    resolution: str = "720p",
) -> str:
    """
    Estimate the cost of a generation before running it (nothing is generated).

    Args:
        kind: 'image' or 'video'.
        model: Image model alias/id (ignored for video).
        count: Number of images.
        image_size: '1K', '2K' or '4K'.
        duration_seconds: Video length.
        resolution: '360p', '720p', '1080p' or '4k'.
    """
    if kind == "image":
        model_id = config.image_model(model)
        est = pricing.image_cost(model_id, image_size, count)
        what = f"{count} x {image_size} image(s) with {model_id}"
    else:
        model_id = config.video_model()
        est = pricing.video_cost(model_id, duration_seconds, resolution)
        what = f"{duration_seconds}s {resolution} video with {model_id}"
    return (f"{what}: {pricing.fmt_usd(est)} (paid tier list price, checked {pricing.PRICES_CHECKED}; "
            "real billing is token-based and may differ)")


def _limits_text() -> str:
    def lim(v):  # 0 = unlimited
        return "no limit" if not v else str(v)
    return (f"images/day {lim(config.daily_image_limit())}, videos/day {lim(config.daily_video_limit())}, "
            f"budget/day {('$' + format(config.daily_budget_usd(), '.2f')) if config.daily_budget_usd() else 'no limit'}, "
            f"ask before videos over ${config.video_confirm_usd():.2f}")


@mcp.tool(structured_output=False)
async def flow_usage_today() -> str:
    """Show today's generation count and estimated spend from the local log."""
    u = ledger.usage_today()
    return (
        f"Today: {u['images']} image(s), {u['videos']} video(s), estimated ~${u['est_cost_usd']:.2f} "
        f"across {u['calls']} successful call(s).\nLimits: {_limits_text()}\nLog: {config.log_path()}"
    )


# ── Studio tools (projects, storyboard, audio, review) ───────────────────────

from . import studio  # noqa: E402,F401  (registers more tools on `mcp`)

# ── Entry Point ───────────────────────────────────────────────────────────────


def main() -> None:
    """Entry point for uvx / python -m google_flow_mcp."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    # Import the packaged module so studio tools register on the same server object.
    from google_flow_mcp.server import main as _main

    _main()
