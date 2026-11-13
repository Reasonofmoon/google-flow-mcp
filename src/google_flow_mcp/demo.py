"""Demo mode (FLOW_DEMO=1): try every workflow with placeholder media.

No request leaves the computer and nothing is billed. Images are labelled cards drawn with
Pillow, videos are those cards with a slow zoom (ffmpeg), audio is a soft tone. The point is to
learn the workflow (projects, ingredients, storyboard, review, assembly) before paying.
"""

from __future__ import annotations

import base64
import hashlib
import io
import math
import struct
import tempfile
import textwrap
import uuid
import wave
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

from PIL import Image, ImageDraw, ImageFont

from . import media

_SIZES = {"1:1": (720, 720), "16:9": (854, 480), "9:16": (480, 854), "2:3": (560, 840), "3:2": (840, 560),
          "3:4": (600, 800), "4:3": (800, 600), "4:5": (640, 800), "5:4": (800, 640), "21:9": (980, 420)}


def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _texts(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    out: list[str] = []
    if isinstance(value, dict):
        if value.get("type") == "text" and value.get("text"):
            out.append(str(value["text"]))
        out += _texts(value.get("content"))
    elif isinstance(value, (list, tuple)):
        for item in value:
            out += _texts(item)
    return out


def _first_image(value: Any) -> Optional[Image.Image]:
    if isinstance(value, (list, tuple)):
        for item in value:
            if isinstance(item, dict) and item.get("type") == "image" and item.get("data"):
                try:
                    return Image.open(io.BytesIO(base64.b64decode(item["data"]))).convert("RGB")
                except Exception:
                    return None
    return None


def _ascii(text: str) -> str:
    """The bundled font is Latin-only, so other scripts are shown as '?'."""
    plain = text.replace("\u2014", "-").replace("\u2013", "-").replace("\u2019", "'").replace("\u00b7", "-")
    return " ".join(plain.encode("ascii", "replace").decode().split())


def _headline(text: str) -> tuple[str, str]:
    """Split a prompt into a short headline (the shot) and the remaining detail."""
    clean = text.strip()
    for marker in ("\n", " Style:", ". "):
        i = clean.find(marker)
        if 12 <= i <= 110:
            return clean[:i].strip(" ."), clean[i:].strip(" .\n")
    return clean[:90], clean[90:].strip()


def card(text: str, size: tuple[int, int], label: str) -> Image.Image:
    """A small scene (sky, sun, hills) colored by the prompt, with the prompt as its caption."""
    w, h = size
    seed = hashlib.sha256(text.encode("utf-8")).digest()
    top = (50 + seed[0] % 110, 60 + seed[1] % 110, 110 + seed[2] % 120)
    bottom = (200 - seed[3] % 80, 150 - seed[4] % 70, 120 + seed[5] % 90)
    img = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(1, h - 1)
        draw.line([(0, y), (w, y)], fill=tuple(int(top[i] * (1 - t) + bottom[i] * t) for i in range(3)))
    r = int(min(w, h) * 0.13)
    cx, cy = int(w * (0.56 + (seed[6] % 26) / 100)), int(h * (0.22 + (seed[7] % 12) / 100))
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 244, 214))
    for layer, (base, shade) in enumerate(((0.60, 0.55), (0.72, 0.32))):
        pts = [(0, h)]
        for i in range(7):
            pts.append((int(w * i / 6), int(h * (base + (seed[8 + layer * 7 + i] % 12) / 100))))
        pts.append((w, h))
        draw.polygon(pts, fill=tuple(int(c * shade) for c in top))

    head, detail = _headline(text)
    hs, ds = max(18, w // 26), max(12, w // 52)
    head_lines = textwrap.wrap(_ascii(head), width=max(14, int(w * 0.88 / (hs * 0.56))))[:2]
    detail_lines = textwrap.wrap(_ascii(detail), width=max(20, int(w * 0.88 / (ds * 0.56))))[:2]
    pad = max(10, w // 60)
    panel_h = int(pad * 2 + len(head_lines) * hs * 1.25 + len(detail_lines) * ds * 1.4)
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(overlay).rectangle([0, h - panel_h, w, h], fill=(8, 10, 18, 170))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(img)
    y = h - panel_h + pad
    for line in head_lines:
        draw.text((pad * 2, y), line, fill=(255, 255, 255), font=_font(hs))
        y += int(hs * 1.25)
    for line in detail_lines:
        draw.text((pad * 2, y), line, fill=(196, 204, 224), font=_font(ds))
        y += int(ds * 1.4)
    bar = max(24, h // 20)
    draw.rectangle([0, 0, w, bar], fill=(0, 0, 0))
    draw.text((10, (bar - max(12, w // 56)) // 2 - 1), f"DEMO · {label} · no API call",
              fill=(255, 220, 90), font=_font(max(12, w // 56)))
    return img


def _fit(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    w, h = size
    scale = max(w / img.width, h / img.height)
    img = img.resize((max(w, int(img.width * scale + 0.5)), max(h, int(img.height * scale + 0.5))))
    left, top = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((left, top, left + w, top + h))


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def tone(seconds: float, freqs: tuple[float, ...] = (220.0,), rate: int = 24000) -> bytes:
    """A quiet sine tone (or chord) as 16-bit mono WAV."""
    n = int(rate * seconds)
    frames = bytearray()
    for i in range(n):
        env = min(1.0, i / (rate * 0.2), (n - i) / (rate * 0.4))
        v = sum(math.sin(2 * math.pi * f * i / rate) for f in freqs) / len(freqs)
        frames += struct.pack("<h", int(v * env * 5000))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))
    return buf.getvalue()


def _seconds(fmt: dict, default: int = 5) -> int:
    raw = str(fmt.get("duration") or "").rstrip("s")
    return max(1, min(15, int(raw))) if raw.isdigit() else default


async def _video(text: str, base: Optional[Image.Image], fmt: dict, label: str) -> bytes:
    w, h = _SIZES["9:16" if fmt.get("aspect_ratio") == "9:16" else "16:9"]
    if fmt.get("resolution") == "360p":
        w, h = (640, 360) if w > h else (360, 640)
    frame = _fit(base, (w, h)) if base is not None else card(text, (w, h), label)
    if base is not None:
        draw = ImageDraw.Draw(frame)
        draw.rectangle([0, 0, w, 26], fill=(0, 0, 0))
        draw.text((10, 5), f"DEMO · {label} · no API call", fill=(255, 220, 90), font=_font(14))
    secs = _seconds(fmt)
    with tempfile.TemporaryDirectory(prefix="flow_demo_") as td:
        png, out = Path(td) / "frame.png", Path(td) / "out.mp4"
        frame.save(png)
        zoom = (f"zoompan=z='min(zoom+0.0012,1.15)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                f":s={w}x{h}:fps=24,format=yuv420p")
        await media.run(["-y", "-loop", "1", "-framerate", "24", "-i", str(png),
                         "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=44100",
                         "-t", str(secs), "-vf", zoom, "-af", "volume=0.04",
                         "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-b:a", "64k",
                         "-shortest", str(out)])
        return out.read_bytes()


def _interaction(kind: str, data: bytes, mime: str) -> SimpleNamespace:
    item = SimpleNamespace(type=kind, data=base64.b64encode(data).decode("ascii"), uri=None, mime_type=mime)
    return SimpleNamespace(id=f"demo_{uuid.uuid4().hex[:12]}", status="completed", output_text="",
                           steps=[SimpleNamespace(type="model_output", content=[item])])


class _Interactions:
    async def create(self, **kw: Any) -> SimpleNamespace:
        model = str(kw.get("model") or "")
        fmt = kw.get("response_format") or {}
        if isinstance(fmt, list):
            fmt = fmt[0] if fmt else {}
        text = " ".join(_texts(kw.get("input"))).strip() or "(no prompt)"
        if "tts" in model:
            return _interaction("audio", tone(max(1.5, len(text) / 14), (180.0,)), "audio/wav")
        if model.startswith("lyria"):
            return _interaction("audio", tone(12, (261.6, 329.6, 392.0)), "audio/wav")
        if fmt.get("type") == "video" or "omni" in model or "veo" in model:
            label = "edit/extend" if kw.get("previous_interaction_id") else "video"
            return _interaction("video", await _video(text, _first_image(kw.get("input")), fmt, label), "video/mp4")
        size = _SIZES.get(str(fmt.get("aspect_ratio") or "1:1"), (720, 720))
        return _interaction("image", _png(card(text, size, "image")), "image/png")


class _Files:
    async def upload(self, **kw: Any) -> SimpleNamespace:
        return SimpleNamespace(name="files/demo", uri="demo://uploaded-file", state="ACTIVE")

    async def get(self, **kw: Any) -> SimpleNamespace:
        return SimpleNamespace(name=kw.get("name", "files/demo"), state="ACTIVE")

    async def download(self, **kw: Any) -> bytes:
        return b""


class DemoClient:
    """Stands in for genai.Client: same call shapes, local placeholder results."""

    def __init__(self) -> None:
        self.aio = SimpleNamespace(interactions=_Interactions(), files=_Files())


NOTICE = ("DEMO MODE (FLOW_DEMO=1): results are local placeholders. Nothing is sent to Google and "
          "nothing is billed. Remove FLOW_DEMO and set GOOGLE_API_KEY for real generation.")
