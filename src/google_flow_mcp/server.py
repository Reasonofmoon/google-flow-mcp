"""Google Flow MCP server — 6 tools for Google AI image and video generation."""

from __future__ import annotations

import asyncio
import io
import mimetypes
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from google import genai
from google.genai import types
from mcp.server.fastmcp import FastMCP
from PIL import Image as PILImage

# ── Constants ────────────────────────────────────────────────────────────────

MODEL_IMAGE_PRO = "gemini-3-pro-image"        # Nano Banana Pro
MODEL_IMAGE_FLASH = "gemini-3.1-flash-image"  # Nano Banana 2
MODEL_VIDEO = "veo-3.1-generate-preview"      # Veo 3.1

VIDEO_POLL_INTERVAL = 10   # seconds between Veo status polls
VIDEO_POLL_TIMEOUT = 600   # 10-minute max wait for video generation

# ── FastMCP Instance ─────────────────────────────────────────────────────────

mcp = FastMCP(
    name="google-flow-mcp",
    instructions=(
        "Provides 6 tools for Google AI image and video generation. "
        "Image tools use Nano Banana Pro (gemini-3-pro-image, high quality) or "
        "Nano Banana 2 (gemini-3.1-flash-image, fast). "
        "Video tools use Veo 3.1 (veo-3.1-generate-preview) with native audio. "
        "Image generation works on the free tier. "
        "Video generation requires a paid Google AI API plan. "
        "Outputs are saved to ~/google_flow_outputs/ by default (override with FLOW_OUTPUT_DIR)."
    ),
)

# ── Client ────────────────────────────────────────────────────────────────────

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "GOOGLE_API_KEY environment variable is required. "
            "Get a free key at https://aistudio.google.com/apikey"
        )
    return genai.Client(api_key=api_key)


def get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = _get_client()
    return _client


# ── File Helpers ──────────────────────────────────────────────────────────────


def _output_dir() -> Path:
    base = os.environ.get("FLOW_OUTPUT_DIR") or str(Path.home() / "google_flow_outputs")
    path = Path(base)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _timestamped(prefix: str, ext: str, out: Optional[Path] = None) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return (out or _output_dir()) / f"{prefix}_{ts}.{ext}"


def _save_image(image_obj, path: Path) -> None:
    """Save a generated image to disk, handling multiple SDK response shapes."""
    if hasattr(image_obj, "save"):
        image_obj.save(str(path))
    elif getattr(image_obj, "image_bytes", None):
        PILImage.open(io.BytesIO(image_obj.image_bytes)).save(str(path))
    elif getattr(image_obj, "_image_bytes", None):
        PILImage.open(io.BytesIO(image_obj._image_bytes)).save(str(path))
    else:
        raise RuntimeError(f"Cannot save image of type {type(image_obj).__name__}")


def _load_image_bytes(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def _mime(path: str) -> str:
    mime, _ = mimetypes.guess_type(path)
    return mime or "image/png"


def _resolve_image_model(model: str) -> str:
    return MODEL_IMAGE_FLASH if model.lower() in ("flash", "2") else MODEL_IMAGE_PRO


async def _poll_operation(client: genai.Client, operation) -> object:
    """Poll a Veo long-running operation until done or timeout."""
    deadline = time.monotonic() + VIDEO_POLL_TIMEOUT
    while not operation.done:
        if time.monotonic() > deadline:
            raise TimeoutError(
                f"Video generation timed out after {VIDEO_POLL_TIMEOUT // 60} minutes. "
                "Try a shorter duration or check the Google AI console."
            )
        await asyncio.sleep(VIDEO_POLL_INTERVAL)
        operation = await client.aio.operations.get(operation)
    if getattr(operation, "error", None) and operation.error.message:
        raise RuntimeError(f"Video generation failed: {operation.error.message}")
    return operation


def _collect_video_results(operation, out: Path, ts: str) -> tuple[list[str], list[str]]:
    """Extract saved paths and/or URIs from a completed video operation."""
    saved, uris = [], []
    videos = getattr(operation.response, "generated_videos", [])
    for i, gen_video in enumerate(videos):
        vid = gen_video.video
        vid_bytes = getattr(vid, "video_bytes", None)
        uri = getattr(vid, "uri", None)
        if vid_bytes:
            path = out / f"flow_video_{ts}_{i}.mp4"
            path.write_bytes(vid_bytes)
            saved.append(str(path))
        elif uri:
            uris.append(uri)
    return saved, uris


def _format_video_result(saved: list[str], uris: list[str]) -> str:
    parts = []
    if saved:
        parts.append("Saved videos:\n" + "\n".join(saved))
    if uris:
        parts.append(
            "Video URI(s) (available for 2 days on Google servers):\n" + "\n".join(uris)
        )
    parts.append("Note: All Veo videos are SynthID-watermarked by Google.")
    return "\n\n".join(parts)


# ── Tool 1: Text → Image ─────────────────────────────────────────────────────


@mcp.tool()
async def flow_generate_image(
    prompt: str,
    model: str = "pro",
    number_of_images: int = 1,
    aspect_ratio: str = "1:1",
    negative_prompt: Optional[str] = None,
    output_dir: Optional[str] = None,
) -> str:
    """
    Generate 1–4 images from a text prompt using Google AI.

    Args:
        prompt: Detailed description of the image(s) to create.
        model: 'pro' for Nano Banana Pro (high quality) or 'flash' for Nano Banana 2 (fast).
        number_of_images: How many images to generate (1–4).
        aspect_ratio: '1:1', '3:4', '4:3', '9:16', or '16:9'.
        negative_prompt: What to exclude from the generated images.
        output_dir: Override the output directory (default: ~/google_flow_outputs).

    Returns:
        Paths to the saved image files.
    """
    client = get_client()
    model_id = _resolve_image_model(model)
    n = max(1, min(4, number_of_images))
    out = Path(output_dir) if output_dir else _output_dir()
    out.mkdir(parents=True, exist_ok=True)

    response = await client.aio.models.generate_images(
        model=model_id,
        prompt=prompt,
        config=types.GenerateImagesConfig(
            number_of_images=n,
            aspect_ratio=aspect_ratio,
            negative_prompt=negative_prompt,
        ),
    )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    paths = []
    for i, gen_img in enumerate(response.generated_images):
        path = out / f"flow_image_{ts}_{i}.png"
        _save_image(gen_img.image, path)
        paths.append(str(path))

    return f"Generated {len(paths)} image(s):\n" + "\n".join(paths)


# ── Tool 2: Edit Image ────────────────────────────────────────────────────────


@mcp.tool()
async def flow_edit_image(
    image_path: str,
    prompt: str,
    edit_mode: str = "inpaint_insertion",
    model: str = "pro",
    mask_mode: str = "MASK_MODE_BACKGROUND",
    output_dir: Optional[str] = None,
) -> str:
    """
    Edit an existing image using a natural language instruction.

    Args:
        image_path: Absolute path to the source image file.
        prompt: Natural language description of the edit to apply.
        edit_mode: 'inpaint_insertion' (add), 'inpaint_removal' (remove),
                   'outpaint' (expand canvas), 'bgswap' (replace background).
        model: 'pro' for Nano Banana Pro or 'flash' for Nano Banana 2.
        mask_mode: Auto-mask strategy — 'MASK_MODE_BACKGROUND', 'MASK_MODE_FOREGROUND',
                   or 'MASK_MODE_SEMANTIC'.
        output_dir: Override the output directory (default: ~/google_flow_outputs).

    Returns:
        Path to the edited image file.
    """
    client = get_client()
    model_id = _resolve_image_model(model)
    out = Path(output_dir) if output_dir else _output_dir()
    out.mkdir(parents=True, exist_ok=True)

    _edit_mode_map = {
        "inpaint_insertion": "EDIT_MODE_INPAINT_INSERTION",
        "inpaint_removal": "EDIT_MODE_INPAINT_REMOVAL",
        "outpaint": "EDIT_MODE_OUTPAINT",
        "bgswap": "EDIT_MODE_BGSWAP",
    }
    sdk_edit_mode = _edit_mode_map.get(edit_mode, edit_mode)

    raw_ref = types.RawReferenceImage(
        reference_id=0,
        reference_image=types.Image(
            image_bytes=_load_image_bytes(image_path),
            mime_type=_mime(image_path),
        ),
    )
    mask_ref = types.MaskReferenceImage(
        reference_id=1,
        config=types.MaskReferenceConfig(mask_mode=mask_mode),
    )

    response = await client.aio.models.edit_image(
        model=model_id,
        prompt=prompt,
        reference_images=[raw_ref, mask_ref],
        config=types.EditImageConfig(
            edit_mode=sdk_edit_mode,
            number_of_images=1,
        ),
    )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    path = out / f"flow_edit_{ts}.png"
    _save_image(response.generated_images[0].image, path)
    return f"Edited image saved to:\n{path}"


# ── Tool 3: Generate with Reference Images ────────────────────────────────────


@mcp.tool()
async def flow_generate_image_with_references(
    prompt: str,
    reference_image_paths: list[str],
    model: str = "pro",
    aspect_ratio: str = "1:1",
    number_of_images: int = 1,
    output_dir: Optional[str] = None,
) -> str:
    """
    Generate an image guided by up to 14 reference images.

    The model uses the reference images for style, composition, and subject guidance
    while following the text prompt.

    Args:
        prompt: Description of the image to generate.
        reference_image_paths: List of paths to reference image files (max 14).
        model: 'pro' for Nano Banana Pro or 'flash' for Nano Banana 2.
        aspect_ratio: '1:1', '3:4', '4:3', '9:16', or '16:9'.
        number_of_images: How many images to generate (1–4).
        output_dir: Override the output directory (default: ~/google_flow_outputs).

    Returns:
        Paths to the generated image files.
    """
    if len(reference_image_paths) > 14:
        raise ValueError(
            f"Maximum 14 reference images allowed; got {len(reference_image_paths)}."
        )
    if not reference_image_paths:
        raise ValueError("At least one reference image path is required.")

    client = get_client()
    model_id = _resolve_image_model(model)
    n = max(1, min(4, number_of_images))
    out = Path(output_dir) if output_dir else _output_dir()
    out.mkdir(parents=True, exist_ok=True)

    reference_images = [
        types.RawReferenceImage(
            reference_id=i,
            reference_image=types.Image(
                image_bytes=_load_image_bytes(ref_path),
                mime_type=_mime(ref_path),
            ),
        )
        for i, ref_path in enumerate(reference_image_paths)
    ]

    response = await client.aio.models.generate_images(
        model=model_id,
        prompt=prompt,
        reference_images=reference_images,
        config=types.GenerateImagesConfig(
            number_of_images=n,
            aspect_ratio=aspect_ratio,
        ),
    )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    paths = []
    for i, gen_img in enumerate(response.generated_images):
        path = out / f"flow_ref_image_{ts}_{i}.png"
        _save_image(gen_img.image, path)
        paths.append(str(path))

    return (
        f"Generated {len(paths)} image(s) using {len(reference_image_paths)} reference(s):\n"
        + "\n".join(paths)
    )


# ── Tool 4: Text → Video ─────────────────────────────────────────────────────


@mcp.tool()
async def flow_generate_video(
    prompt: str,
    duration_seconds: int = 8,
    aspect_ratio: str = "16:9",
    negative_prompt: Optional[str] = None,
    anchor_frame_path: Optional[str] = None,
    enhance_prompt: bool = True,
    output_dir: Optional[str] = None,
) -> str:
    """
    Generate a cinematic video with native audio from a text prompt using Veo 3.1.

    Requires a paid Google AI API plan. Generated videos are SynthID-watermarked
    and stored on Google servers for 2 days.

    Args:
        prompt: Cinematic description of the video — include camera movement, lighting,
                subject action, and mood for best results.
        duration_seconds: Video duration in seconds (typically 5–8).
        aspect_ratio: '16:9' for landscape or '9:16' for portrait/mobile.
        negative_prompt: What to exclude from the video.
        anchor_frame_path: Optional path to an image to use as the first frame.
        enhance_prompt: Whether to allow Veo to rewrite/enhance your prompt.
        output_dir: Override the output directory (default: ~/google_flow_outputs).

    Returns:
        Paths or URIs to the generated video(s).
    """
    client = get_client()
    out = Path(output_dir) if output_dir else _output_dir()
    out.mkdir(parents=True, exist_ok=True)

    config = types.GenerateVideosConfig(
        duration_seconds=duration_seconds,
        aspect_ratio=aspect_ratio,
        negative_prompt=negative_prompt,
        enhance_prompt=enhance_prompt,
    )

    kwargs: dict = dict(model=MODEL_VIDEO, prompt=prompt, config=config)

    if anchor_frame_path:
        kwargs["image"] = types.Image(
            image_bytes=_load_image_bytes(anchor_frame_path),
            mime_type=_mime(anchor_frame_path),
        )

    operation = await client.aio.models.generate_videos(**kwargs)
    operation = await _poll_operation(client, operation)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    saved, uris = _collect_video_results(operation, out, ts)
    return _format_video_result(saved, uris)


# ── Tool 5: Extend Video ──────────────────────────────────────────────────────


@mcp.tool()
async def flow_extend_video(
    video_path: str,
    prompt: str,
    duration_seconds: int = 8,
    aspect_ratio: str = "16:9",
    output_dir: Optional[str] = None,
) -> str:
    """
    Extend an existing Veo 3.1 video clip with additional generated content.

    Requires a paid Google AI API plan. The extended video is SynthID-watermarked.

    Args:
        video_path: Absolute path to the source MP4 video file to extend.
        prompt: Description of how to continue the video after the source clip ends.
        duration_seconds: Duration of the generated extension in seconds (typically 5–8).
        aspect_ratio: Must match the source video — '16:9' or '9:16'.
        output_dir: Override the output directory (default: ~/google_flow_outputs).

    Returns:
        Path or URI to the extended video.
    """
    client = get_client()
    out = Path(output_dir) if output_dir else _output_dir()
    out.mkdir(parents=True, exist_ok=True)

    with open(video_path, "rb") as f:
        video_bytes = f.read()

    operation = await client.aio.models.generate_videos(
        model=MODEL_VIDEO,
        prompt=prompt,
        video=types.Video(video_bytes=video_bytes, mime_type="video/mp4"),
        config=types.GenerateVideosConfig(
            duration_seconds=duration_seconds,
            aspect_ratio=aspect_ratio,
        ),
    )
    operation = await _poll_operation(client, operation)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    saved, uris = _collect_video_results(operation, out, ts)
    return _format_video_result(saved, uris)


# ── Tool 6: Image → Video Pipeline ───────────────────────────────────────────


@mcp.tool()
async def flow_image_to_video(
    video_prompt: str,
    image_prompt: Optional[str] = None,
    image_path: Optional[str] = None,
    image_model: str = "pro",
    duration_seconds: int = 8,
    aspect_ratio: str = "16:9",
    negative_prompt: Optional[str] = None,
    output_dir: Optional[str] = None,
) -> str:
    """
    Full pipeline: generate or use an image with Nano Banana Pro, then animate it with Veo 3.1.

    Provide either image_prompt (to generate a new anchor image) or image_path (to use an
    existing image). The anchor image becomes the first frame of the video.

    Requires a paid Google AI API plan for the video step.

    Args:
        video_prompt: Cinematic description of the video animation — how the scene moves.
        image_prompt: Text prompt to generate the anchor image (if image_path is not given).
        image_path: Path to an existing image to use as the anchor frame.
        image_model: 'pro' (Nano Banana Pro, recommended) or 'flash' (Nano Banana 2).
        duration_seconds: Video duration in seconds (typically 5–8).
        aspect_ratio: '16:9' for landscape or '9:16' for portrait.
        negative_prompt: What to exclude from both the image and video.
        output_dir: Override the output directory (default: ~/google_flow_outputs).

    Returns:
        Paths to the generated anchor image and the final video.
    """
    if not image_prompt and not image_path:
        raise ValueError("Provide either image_prompt or image_path.")

    client = get_client()
    out = Path(output_dir) if output_dir else _output_dir()
    out.mkdir(parents=True, exist_ok=True)
    results: list[str] = []

    # Step 1 — Generate or load the anchor image
    if image_path:
        anchor_path = image_path
    else:
        model_id = _resolve_image_model(image_model)
        img_response = await client.aio.models.generate_images(
            model=model_id,
            prompt=image_prompt,
            config=types.GenerateImagesConfig(
                number_of_images=1,
                aspect_ratio=aspect_ratio,
                negative_prompt=negative_prompt,
            ),
        )
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        anchor = out / f"flow_anchor_{ts}.png"
        _save_image(img_response.generated_images[0].image, anchor)
        anchor_path = str(anchor)
        results.append(f"Anchor image:\n{anchor_path}")

    # Step 2 — Animate with Veo 3.1
    operation = await client.aio.models.generate_videos(
        model=MODEL_VIDEO,
        prompt=video_prompt,
        image=types.Image(
            image_bytes=_load_image_bytes(anchor_path),
            mime_type=_mime(anchor_path),
        ),
        config=types.GenerateVideosConfig(
            duration_seconds=duration_seconds,
            aspect_ratio=aspect_ratio,
            negative_prompt=negative_prompt,
        ),
    )
    operation = await _poll_operation(client, operation)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    saved, uris = _collect_video_results(operation, out, ts)
    results.append(_format_video_result(saved, uris))

    return "\n\n".join(results)


# ── Entry Point ───────────────────────────────────────────────────────────────


def main() -> None:
    """Entry point for uvx / python -m google_flow_mcp."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
