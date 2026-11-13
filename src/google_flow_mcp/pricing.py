"""Estimated Gemini API prices (paid tier, Standard, USD).

Source: https://aistudio.google.com/docs/pricing, checked 2026-11-13.
These are estimates for guidance only. Google bills by tokens, so real charges
can differ (thinking tokens, retries, input images). Free tier is
"Not available" for every model listed here, so the API key needs billing.

Override or add models with FLOW_PRICES_FILE (JSON in the same shape).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

PRICES_CHECKED = "2026-11-13"

# USD per output image, by image_size
IMAGE_PRICES: dict[str, dict[str, float]] = {
    "gemini-3-pro-image": {"1K": 0.134, "2K": 0.134, "4K": 0.24},
    "gemini-nano-banana-2.1": {"1K": 0.0336, "2K": 0.0504, "4K": 0.113},
    "gemini-3.1-flash-image": {"0.5K": 0.045, "1K": 0.067, "2K": 0.101, "4K": 0.151},
    "gemini-3.1-flash-lite-image": {"1K": 0.0336},
}

# USD per second of output video, by resolution
VIDEO_PRICES: dict[str, dict[str, float]] = {
    "gemini-omni-1.2-flash": {"360p": 0.023, "720p": 0.07, "1080p": 0.104, "4k": 0.209},
}


# USD per request
MUSIC_PRICES: dict[str, float] = {
    "lyria-3-clip-preview": 0.04,
    "lyria-3.5": 0.08,
    "lyria-3-pro-preview": 0.08,
}

# USD per second of speech (free tier available; these are paid-tier rates
# through 2026-12-31, and they double on 2027-01-01)
SPEECH_PRICES: dict[str, float] = {
    "gemini-3.8-flash-tts": 0.000225,
    "gemini-3.8-flash-lite-tts": 0.00015,
}


def _load_overrides() -> None:
    custom = os.environ.get("FLOW_PRICES_FILE", "").strip()
    if not custom:
        return
    try:
        data = json.loads(Path(custom).expanduser().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    IMAGE_PRICES.update(data.get("image", {}))
    VIDEO_PRICES.update(data.get("video", {}))
    MUSIC_PRICES.update(data.get("music", {}))
    SPEECH_PRICES.update(data.get("speech", {}))


def image_cost(model: str, image_size: str = "1K", count: int = 1) -> float | None:
    _load_overrides()
    table = IMAGE_PRICES.get(model)
    if not table:
        return None
    price = table.get(image_size.upper()) or table.get(image_size) or max(table.values())
    return round(price * max(1, count), 4)


def video_cost(model: str, seconds: int, resolution: str = "720p") -> float | None:
    _load_overrides()
    table = VIDEO_PRICES.get(model)
    if not table:
        return None
    price = table.get(resolution.lower()) or table.get("720p") or max(table.values())
    return round(price * max(1, seconds), 4)


def music_cost(model: str) -> float | None:
    _load_overrides()
    return MUSIC_PRICES.get(model)


def speech_cost(model: str, seconds: float) -> float | None:
    _load_overrides()
    rate = SPEECH_PRICES.get(model)
    return None if rate is None else round(rate * max(1.0, seconds), 4)


def fmt_usd(value: float | None) -> str:
    if value is None:
        return "unknown (model not in price table)"
    return f"~${value:.2f}" if value >= 0.01 or value == 0 else f"~${value:.4f}"
