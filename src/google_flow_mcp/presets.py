"""Aspect-ratio / size presets and style presets.

Add your own in a JSON file and point FLOW_PRESETS_FILE at it:

{
  "formats": {"tpt-cover": {"aspect_ratio": "1:1", "image_size": "2K", "note": "TPT cover"}},
  "styles":  {"moonlight": "soft pastel watercolor, warm lighting, children's book style"}
}
"""

from __future__ import annotations

import json
from typing import Optional

from . import config

FORMATS: dict[str, dict] = {
    "square": {"aspect_ratio": "1:1", "image_size": "1K", "note": "Generic square"},
    "youtube-thumbnail": {"aspect_ratio": "16:9", "image_size": "2K", "video_aspect_ratio": "16:9",
                          "note": "YouTube thumbnail / landscape video"},
    "shorts": {"aspect_ratio": "9:16", "image_size": "2K", "video_aspect_ratio": "9:16",
               "note": "YouTube Shorts, Reels, TikTok"},
    "pinterest-pin": {"aspect_ratio": "2:3", "image_size": "2K", "video_aspect_ratio": "9:16",
                      "note": "Pinterest standard pin (1000x1500)"},
    "instagram-post": {"aspect_ratio": "4:5", "image_size": "2K", "note": "Instagram portrait post"},
    "worksheet": {"aspect_ratio": "3:4", "image_size": "2K", "note": "Printable worksheet / book page"},
    "banner": {"aspect_ratio": "21:9", "image_size": "2K", "note": "Wide web banner"},
}

STYLES: dict[str, str] = {
    "photo": "photorealistic, natural lighting, shot on a full-frame camera, sharp focus",
    "flat-illustration": "clean flat vector illustration, simple shapes, limited color palette, no gradients",
    "watercolor": "soft watercolor painting, visible paper texture, gentle color bleeds",
    "kids-book": "warm children's picture-book illustration, friendly characters, soft colors",
    "3d-clay": "cute 3D clay render, soft studio lighting, rounded shapes",
    "infographic": "clear infographic layout, legible labels, strong visual hierarchy, white background",
    "cinematic": "cinematic, dramatic lighting, shallow depth of field, film grain",
}


# Camera moves, as in Flow's camera controls. Written the way Omni's prompt guide suggests.
CAMERA: dict[str, str] = {
    "static": "locked-off static camera on a tripod, no camera movement",
    "push-in": "slow dolly push-in toward the subject",
    "pull-out": "slow dolly pull-back that reveals the surroundings",
    "pan-left": "smooth pan from right to left",
    "pan-right": "smooth pan from left to right",
    "tilt-up": "slow tilt upward",
    "tilt-down": "slow tilt downward",
    "orbit": "camera orbits around the subject in a smooth arc",
    "tracking": "tracking shot that follows the subject at the same speed",
    "crane-up": "crane shot rising up and away",
    "drone": "aerial drone shot gliding forward over the scene",
    "handheld": "handheld camera with slight natural shake, documentary feel",
    "pov": "first-person point-of-view shot",
    "dolly-zoom": "dolly zoom (vertigo effect): camera moves back while zooming in",
    "macro": "extreme close-up macro shot with shallow depth of field",
    "slow-motion": "slow motion, 120 fps look",
    "timelapse": "timelapse with fast-moving clouds and light",
    "whip-pan": "fast whip pan with motion blur",
}


def camera_phrase(name: Optional[str]) -> str:
    """A preset name becomes its phrase; anything else is used as written."""
    if not name:
        return ""
    return CAMERA.get(name.strip().lower(), name.strip())


def _custom() -> dict:
    path = config.presets_file()
    if not path:
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def all_formats() -> dict[str, dict]:
    return {**FORMATS, **_custom().get("formats", {})}


def all_styles() -> dict[str, str]:
    return {**STYLES, **_custom().get("styles", {})}


def resolve_format(preset: Optional[str]) -> dict:
    if not preset:
        return {}
    formats = all_formats()
    if preset not in formats:
        raise ValueError(f"Unknown preset '{preset}'. Available: {', '.join(sorted(formats))}")
    return formats[preset]


def apply_style(prompt: str, style: Optional[str]) -> str:
    if not style:
        return prompt
    styles = all_styles()
    if style not in styles:
        raise ValueError(f"Unknown style '{style}'. Available: {', '.join(sorted(styles))}")
    return f"{prompt}\n\nStyle: {styles[style]}"
