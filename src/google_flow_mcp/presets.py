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
