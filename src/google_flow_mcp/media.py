"""Local media helpers: thumbnails, contact sheets, and ffmpeg (frames, concat, mix).

ffmpeg lookup order: FLOW_FFMPEG, `ffmpeg` on PATH, then the binary bundled with
the `imageio-ffmpeg` package (installed as a dependency, so it works out of the box).
"""

from __future__ import annotations

import asyncio
import io
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional, Sequence

from PIL import Image, ImageDraw, ImageFont

from . import config

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def ffmpeg_exe() -> Optional[str]:
    custom = config.ffmpeg_path()
    if custom and Path(custom).exists():
        return custom
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def _run_sync(args: list[str], timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, timeout=timeout,
                          stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW)


async def run(args: Sequence[str], timeout: int = 900, check: bool = True) -> str:
    """Run ffmpeg and return its stderr text."""
    exe = ffmpeg_exe()
    if not exe:
        raise RuntimeError("ffmpeg not found. Install ffmpeg or set FLOW_FFMPEG to its full path.")
    proc = await asyncio.to_thread(_run_sync, [exe, "-hide_banner", "-nostdin", *args], timeout)
    err = proc.stderr.decode("utf-8", "replace")
    if check and proc.returncode != 0:
        raise RuntimeError("ffmpeg failed: " + err.strip()[-800:])
    return err


async def probe(path: str | Path) -> dict:
    """Duration, size and audio presence, parsed from `ffmpeg -i` output."""
    err = await run(["-i", str(path)], check=False)
    duration = 0.0
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", err)
    if m:
        duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    size = re.search(r"Video:.*?,\s*(\d{2,5})x(\d{2,5})[\s,\[]", err)
    return {
        "duration": round(duration, 3),
        "has_video": bool(re.search(r"Stream #.*Video:", err)),
        "has_audio": bool(re.search(r"Stream #.*Audio:", err)),
        "width": int(size.group(1)) if size else 0,
        "height": int(size.group(2)) if size else 0,
    }


# ── Images ────────────────────────────────────────────────────────────────────


def thumbnail_bytes(path: str | Path, max_side: int = 768) -> bytes:
    with Image.open(path) as im:
        im = im.convert("RGB")
        im.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=78)
        return buf.getvalue()


def safe_thumbnail(path: str | Path, max_side: int = 768) -> Optional[bytes]:
    try:
        return thumbnail_bytes(path, max_side)
    except Exception:
        return None


def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def contact_sheet(items: Sequence[tuple[str, Optional[str | Path]]], cols: int = 3, cell_w: int = 360) -> bytes:
    """Grid of labelled images as JPEG bytes. Missing images get a grey placeholder."""
    if not items:
        raise ValueError("contact_sheet needs at least one item")
    loaded: list[tuple[str, Optional[Image.Image]]] = []
    ratio = 9 / 16
    for label, path in items:
        im = None
        if path:
            try:
                with Image.open(path) as src:
                    im = src.convert("RGB")
            except Exception:
                im = None
        loaded.append((label, im))
    first = next((im for _, im in loaded if im is not None), None)
    if first is not None:
        ratio = first.height / first.width
    cell_h = max(40, int(cell_w * ratio))
    cols = max(1, min(cols, len(loaded)))
    rows = (len(loaded) + cols - 1) // cols
    gap = 6
    sheet = Image.new("RGB", (cols * cell_w + (cols + 1) * gap, rows * cell_h + (rows + 1) * gap), (24, 24, 28))
    draw = ImageDraw.Draw(sheet)
    font = _font(15)
    for i, (label, im) in enumerate(loaded):
        x = gap + (i % cols) * (cell_w + gap)
        y = gap + (i // cols) * (cell_h + gap)
        if im is None:
            draw.rectangle([x, y, x + cell_w, y + cell_h], fill=(60, 60, 66))
        else:
            fit = im.copy()
            fit.thumbnail((cell_w, cell_h))
            sheet.paste(fit, (x + (cell_w - fit.width) // 2, y + (cell_h - fit.height) // 2))
        text = label[:40]
        box = draw.textbbox((0, 0), text, font=font)
        lw, lh = (box[2] - box[0]) + 12, (box[3] - box[1]) + 10
        left = x + cell_w - lw  # top-right: clear of titles (top-left) and captions (bottom)
        draw.rectangle([left, y, x + cell_w, y + lh], fill=(0, 0, 0))
        draw.text((left + 6, y + 3), text, fill=(255, 255, 255), font=font)
    buf = io.BytesIO()
    sheet.save(buf, "JPEG", quality=76)
    return buf.getvalue()


# ── Video ─────────────────────────────────────────────────────────────────────


async def extract_frames(video: str | Path, n: int, out_dir: Path, width: int = 480) -> list[tuple[float, Path]]:
    info = await probe(video)
    d = info["duration"]
    n = max(1, min(12, n))
    times = [d * (i + 0.5) / n for i in range(n)] if d > 0 else [0.0]
    frames: list[tuple[float, Path]] = []
    for i, t in enumerate(times):
        out = out_dir / f"frame_{i:02d}.jpg"
        await run(["-y", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1",
                   "-vf", f"scale={width}:-2", "-q:v", "4", "-update", "1", str(out)], check=False)
        if out.exists():
            frames.append((t, out))
    return frames


async def video_sheet(video: str | Path, frames: int = 6, cols: int = 3) -> tuple[Optional[bytes], dict]:
    """Contact sheet of evenly spaced frames, so the assistant can 'watch' a clip."""
    info = await probe(video)
    with tempfile.TemporaryDirectory(prefix="flow_frames_") as td:
        got = await extract_frames(video, frames, Path(td))
        if not got:
            return None, info
        return contact_sheet([(f"{t:.1f}s", p) for t, p in got], cols=cols), info


async def middle_frame(video: str | Path, out: Path) -> Optional[Path]:
    info = await probe(video)
    t = info["duration"] / 2 if info["duration"] else 0
    await run(["-y", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1", "-vf", "scale=480:-2",
               "-q:v", "4", "-update", "1", str(out)], check=False)
    return out if out.exists() else None


def _even(v: int) -> int:
    return v - (v % 2)


async def concat(clips: Sequence[dict], out: Path, fps: int = 24) -> dict:
    """Join clips (re-encoded to one size) into `out`.

    Each clip: {"path": ..., "start": seconds or None, "end": seconds or None}.
    Clips without audio get silence so the result always has one audio track.
    """
    if not clips:
        raise ValueError("No clips to join.")
    infos = [await probe(c["path"]) for c in clips]
    base = next((i for i in infos if i["width"] and i["height"]), None)
    w, h = (_even(base["width"]), _even(base["height"])) if base else (1280, 720)
    args: list[str] = []
    filters: list[str] = []
    idx = 0
    total = 0.0
    for i, (clip, info) in enumerate(zip(clips, infos)):
        if not info["has_video"]:
            raise RuntimeError(f"Not a video file: {clip['path']}")
        args += ["-i", str(clip["path"])]
        vi = idx
        idx += 1
        start = max(0.0, float(clip.get("start") or 0))
        end = float(clip.get("end") or 0) or info["duration"]
        if end <= start:
            start, end = 0.0, info["duration"]
        trimmed = start > 0 or bool(clip.get("end"))
        seg = max(0.0, end - start) if end else info["duration"]
        total += seg
        vtrim = f"trim=start={start:.3f}:end={end:.3f},setpts=PTS-STARTPTS," if trimmed else ""
        filters.append(
            f"[{vi}:v]{vtrim}scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},format=yuv420p[v{i}]"
        )
        if info["has_audio"]:
            atrim = f"atrim=start={start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS," if trimmed else ""
            filters.append(f"[{vi}:a]{atrim}aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo[a{i}]")
        else:
            args += ["-f", "lavfi", "-t", f"{max(seg, 0.1):.3f}", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
            filters.append(f"[{idx}:a]aformat=sample_fmts=fltp:channel_layouts=stereo[a{i}]")
            idx += 1
    n = len(clips)
    filters.append("".join(f"[v{i}][a{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[v][a]")
    out.parent.mkdir(parents=True, exist_ok=True)
    await run(["-y", *args, "-filter_complex", ";".join(filters), "-map", "[v]", "-map", "[a]",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "160k",
               "-movflags", "+faststart", str(out)])
    return {"path": str(out), "clips": n, "expected_duration": round(total, 2), "width": w, "height": h}


async def mix(video: Path, out: Path, music: Optional[str | Path] = None,
              narration: Optional[str | Path] = None, music_volume: float = 0.25,
              clip_volume: float = 1.0, narration_volume: float = 1.0) -> dict:
    """Lay music (looped, faded out) and narration over a video's own audio."""
    info = await probe(video)
    d = info["duration"]
    if d <= 0:
        raise RuntimeError(f"Could not read the duration of {video}")
    args = ["-i", str(video)]
    filters: list[str] = []
    labels: list[str] = []
    idx = 1
    if info["has_audio"] and clip_volume > 0:
        filters.append(f"[0:a]volume={clip_volume:.3f}[a0]")
        labels.append("[a0]")
    if music:
        args += ["-stream_loop", "-1", "-i", str(music)]
        fade = f",afade=t=out:st={max(0.0, d - 1.5):.2f}:d=1.5" if d > 3 else ""
        filters.append(f"[{idx}:a]aresample=44100,volume={music_volume:.3f},atrim=end={d:.3f}{fade}[am]")
        labels.append("[am]")
        idx += 1
    if narration:
        args += ["-i", str(narration)]
        filters.append(f"[{idx}:a]aresample=44100,volume={narration_volume:.3f}[an]")
        labels.append("[an]")
        idx += 1
    if not labels:
        raise ValueError("Nothing to mix: give music and/or narration.")
    if len(labels) == 1:
        filters.append(f"{labels[0]}atrim=end={d:.3f}[a]")
    else:
        filters.append("".join(labels) + f"amix=inputs={len(labels)}:duration=longest:normalize=0,atrim=end={d:.3f}[a]")
    out.parent.mkdir(parents=True, exist_ok=True)
    await run(["-y", *args, "-filter_complex", ";".join(filters), "-map", "0:v", "-map", "[a]",
               "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-t", f"{d:.3f}",
               "-movflags", "+faststart", str(out)])
    return {"path": str(out), "duration": d}


def wav_seconds(data: bytes, sample_rate: int = 24000) -> float:
    """Length of 16-bit mono PCM WAV bytes (the TTS default)."""
    return max(0.0, (len(data) - 44) / (sample_rate * 2))
