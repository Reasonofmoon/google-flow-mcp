"""Runtime settings read from environment variables.

Every value can be changed in the ``env`` block of ``claude_desktop_config.json``
without touching the code. Settings are read on each call, so a restart of
Claude Desktop is enough after editing the config.
"""

from __future__ import annotations

import os
from pathlib import Path

# Defaults checked against https://aistudio.google.com/docs (2026-11-13).
DEFAULT_MODEL_IMAGE_PRO = "gemini-3-pro-image"            # Nano Banana Pro
DEFAULT_MODEL_IMAGE_FAST = "gemini-nano-banana-2.1"       # Nano Banana 2.1
DEFAULT_MODEL_IMAGE_LITE = "gemini-3.1-flash-lite-image"  # Nano Banana 2 Lite
DEFAULT_MODEL_VIDEO = "gemini-omni-1.2-flash"             # Veo 3.1 Preview shut down 2026-10-22
DEFAULT_MODEL_MUSIC_CLIP = "lyria-3-clip-preview"         # 30 s clip
DEFAULT_MODEL_MUSIC_SONG = "lyria-3.5"                    # full song
DEFAULT_MODEL_TTS = "gemini-3.8-flash-tts"

IMAGE_MODEL_ALIASES = {
    "pro": "pro",
    "fast": "fast",
    "flash": "fast",
    "2": "fast",
    "2.1": "fast",
    "lite": "lite",
}


def _env(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value or default


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


def image_model(alias: str | None = None) -> str:
    """Resolve 'pro' / 'fast' / 'lite' (or a full model id) to a model id."""
    alias = (alias or _env("FLOW_DEFAULT_IMAGE_MODEL", "fast")).strip()
    key = IMAGE_MODEL_ALIASES.get(alias.lower())
    if key == "pro":
        return _env("FLOW_MODEL_IMAGE_PRO", DEFAULT_MODEL_IMAGE_PRO)
    if key == "fast":
        return _env("FLOW_MODEL_IMAGE_FAST", DEFAULT_MODEL_IMAGE_FAST)
    if key == "lite":
        return _env("FLOW_MODEL_IMAGE_LITE", DEFAULT_MODEL_IMAGE_LITE)
    return alias  # a full model id such as "gemini-3.1-flash-image"


def video_model() -> str:
    return _env("FLOW_MODEL_VIDEO", DEFAULT_MODEL_VIDEO)


def music_model(kind: str = "clip") -> str:
    if kind == "song":
        return _env("FLOW_MODEL_MUSIC_SONG", DEFAULT_MODEL_MUSIC_SONG)
    return _env("FLOW_MODEL_MUSIC_CLIP", DEFAULT_MODEL_MUSIC_CLIP)


def tts_model() -> str:
    return _env("FLOW_MODEL_TTS", DEFAULT_MODEL_TTS)


def projects_dir() -> Path:
    custom = os.environ.get("FLOW_PROJECTS_DIR", "").strip()
    path = Path(custom).expanduser() if custom else output_dir() / "projects"
    path.mkdir(parents=True, exist_ok=True)
    return path


def demo() -> bool:
    """FLOW_DEMO=1: placeholder media, no API calls, nothing billed."""
    return os.environ.get("FLOW_DEMO", "").strip().lower() in ("1", "true", "yes", "on")


def inline_preview() -> bool:
    """Return small previews to the assistant so it can see what was made."""
    return _env("FLOW_INLINE_PREVIEW", "1").lower() not in ("0", "false", "no", "off")


def ffmpeg_path() -> str:
    return os.environ.get("FLOW_FFMPEG", "").strip()


def render_wait_seconds() -> int:
    """How long a storyboard render call waits before handing work to the background."""
    return _env_int("FLOW_RENDER_WAIT_SECONDS", 150)


def render_concurrency() -> int:
    return max(1, _env_int("FLOW_RENDER_CONCURRENCY", 2))


def output_dir(override: str | None = None) -> Path:
    base = override or _env("FLOW_OUTPUT_DIR", str(Path.home() / "google_flow_outputs"))
    path = Path(base).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_path() -> Path:
    custom = os.environ.get("FLOW_LOG_FILE", "").strip()
    if custom:
        p = Path(custom).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
    return output_dir() / "generation_log.jsonl"


def daily_image_limit() -> int:
    """Max images per local day. 0 = no limit."""
    return _env_int("FLOW_DAILY_IMAGE_LIMIT", 100)


def daily_video_limit() -> int:
    """Max video generations per local day. 0 = no limit."""
    return _env_int("FLOW_DAILY_VIDEO_LIMIT", 20)


def daily_budget_usd() -> float:
    """Max estimated spend per local day in USD. 0 = no limit."""
    return _env_float("FLOW_DAILY_BUDGET_USD", 5.0)


def video_confirm_usd() -> float:
    """Video calls estimated above this need confirm_cost=True. 0 = never ask."""
    return _env_float("FLOW_VIDEO_CONFIRM_USD", 0.5)


def presets_file() -> Path | None:
    custom = os.environ.get("FLOW_PRESETS_FILE", "").strip()
    return Path(custom).expanduser() if custom else None
