"""Shared fixtures. Google API calls are mocked; ffmpeg and Pillow run for real."""

from __future__ import annotations

import base64
import io
import os
import subprocess
import tempfile
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image

os.environ.setdefault("GOOGLE_API_KEY", "test-api-key-000")
os.environ["FLOW_OUTPUT_DIR"] = tempfile.mkdtemp()

import google_flow_mcp.server as server  # noqa: E402
from google_flow_mcp import media  # noqa: E402


def png_bytes(color=(200, 60, 60), size=(320, 180)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def wav_bytes(seconds: float = 1.0, rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))
    return buf.getvalue()


PNG = png_bytes()
WAV = wav_bytes()
FAKE_MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 32


def interaction(kind: str, data: bytes, iid: str = "v1_test", mime: str | None = None):
    default = {"image": "image/png", "video": "video/mp4", "audio": "audio/wav"}[kind]
    item = SimpleNamespace(type=kind, data=base64.b64encode(data).decode(), uri=None, mime_type=mime or default)
    return SimpleNamespace(
        id=iid, status="completed", output_text="",
        steps=[SimpleNamespace(type="user_input", content=[]),
               SimpleNamespace(type="model_output", content=[item])],
    )


def text_of(result) -> str:
    """Tools return a string, or [string, Image...] when previews are attached."""
    return result if isinstance(result, str) else result[0]


def write_png(tmp_path: Path, name: str = "in.png", color=(40, 90, 200)) -> str:
    p = tmp_path / name
    p.write_bytes(png_bytes(color))
    return str(p)


@pytest.fixture(scope="session")
def ffmpeg() -> str:
    exe = media.ffmpeg_exe()
    assert exe, "ffmpeg not available (imageio-ffmpeg should provide it)"
    return exe


@pytest.fixture(scope="session")
def clips(tmp_path_factory, ffmpeg) -> dict:
    """A 1 s test clip with sound and a 1 s silent clip, made with ffmpeg's test sources."""
    d = tmp_path_factory.mktemp("media")
    sound, silent = d / "clip.mp4", d / "silent.mp4"
    video_src = ["-f", "lavfi", "-i", "testsrc=size=320x180:rate=24:duration=1"]
    subprocess.run([ffmpeg, "-y", *video_src, "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(sound)],
                   check=True, capture_output=True)
    subprocess.run([ffmpeg, "-y", *video_src, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(silent)],
                   check=True, capture_output=True)
    return {"sound": sound, "silent": silent, "bytes": sound.read_bytes()}


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    server._client = None
    for k in list(os.environ):
        if k.startswith("FLOW_") and k != "FLOW_OUTPUT_DIR":
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("FLOW_OUTPUT_DIR", str(tmp_path))
    yield
    server._client = None


def _client(mocker) -> MagicMock:
    c = MagicMock()
    c.aio.interactions.create = AsyncMock(return_value=interaction("image", PNG))
    c.aio.files.upload = AsyncMock(return_value=SimpleNamespace(name="files/abc", uri="https://x/files/abc", state="ACTIVE"))
    c.aio.files.get = AsyncMock(return_value=SimpleNamespace(name="files/abc", state="ACTIVE"))
    c.aio.files.download = AsyncMock(return_value=FAKE_MP4)
    mocker.patch.object(server, "_get_client", return_value=c)
    return c


@pytest.fixture
def client(mocker) -> MagicMock:
    """Every interaction returns one image unless a test overrides return_value."""
    return _client(mocker)


@pytest.fixture
def studio_client(mocker, clips) -> MagicMock:
    """Answers by model: image, real 1 s video, or WAV audio."""
    c = _client(mocker)
    counter = {"n": 0}

    async def fake_create(**kw):
        model = kw["model"]
        counter["n"] += 1
        if model.startswith("lyria") or "tts" in model:
            return interaction("audio", WAV)
        if "omni" in model:
            return interaction("video", clips["bytes"], iid=f"v1_{counter['n']}")
        return interaction("image", PNG)

    c.aio.interactions.create = AsyncMock(side_effect=fake_create)
    return c
