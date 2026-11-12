"""Unit tests for google_flow_mcp — every Google API call is mocked."""

from __future__ import annotations

import base64
import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

os.environ.setdefault("GOOGLE_API_KEY", "test-api-key-000")
os.environ["FLOW_OUTPUT_DIR"] = tempfile.mkdtemp()

import google_flow_mcp.server as server  # noqa: E402
from google_flow_mcp import config, ledger, presets, pricing  # noqa: E402
from google_flow_mcp.server import (  # noqa: E402
    flow_edit_image,
    flow_estimate_cost,
    flow_extend_video,
    flow_generate_image,
    flow_generate_image_with_references,
    flow_generate_video,
    flow_image_to_video,
    flow_list_presets,
    flow_usage_today,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 32


def _interaction(kind: str, data: bytes, iid: str = "v1_test", mime: str | None = None):
    item = SimpleNamespace(type=kind, data=base64.b64encode(data).decode(), uri=None,
                           mime_type=mime or ("image/png" if kind == "image" else "video/mp4"))
    return SimpleNamespace(
        id=iid, status="completed", output_text="",
        steps=[SimpleNamespace(type="user_input", content=[]),
               SimpleNamespace(type="model_output", content=[item])],
    )


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    server._client = None
    for k in list(os.environ):
        if k.startswith("FLOW_") and k != "FLOW_OUTPUT_DIR":
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("FLOW_OUTPUT_DIR", str(tmp_path))
    yield
    server._client = None


@pytest.fixture
def client(mocker):
    c = MagicMock()
    c.aio.interactions.create = AsyncMock(return_value=_interaction("image", PNG))
    c.aio.files.upload = AsyncMock(return_value=SimpleNamespace(name="files/abc", uri="https://x/files/abc", state="ACTIVE"))
    c.aio.files.get = AsyncMock(return_value=SimpleNamespace(name="files/abc", state="ACTIVE"))
    c.aio.files.download = AsyncMock(return_value=MP4)
    mocker.patch.object(server, "_get_client", return_value=c)
    return c


def _log(tmp_path: Path) -> list[dict]:
    p = tmp_path / "generation_log.jsonl"
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


def _png(tmp_path: Path, name: str = "in.png") -> str:
    p = tmp_path / name
    p.write_bytes(PNG)
    return str(p)


# ── Models from env ──────────────────────────────────────────────────────────


async def test_default_image_model_is_fast(client, tmp_path):
    await flow_generate_image(prompt="a red apple")
    kw = client.aio.interactions.create.call_args.kwargs
    assert kw["model"] == config.DEFAULT_MODEL_IMAGE_FAST
    assert kw["input"] == "a red apple"
    assert kw["response_format"]["type"] == "image"


async def test_model_aliases_and_env_override(client, monkeypatch):
    await flow_generate_image(prompt="x", model="pro")
    assert client.aio.interactions.create.call_args.kwargs["model"] == config.DEFAULT_MODEL_IMAGE_PRO
    monkeypatch.setenv("FLOW_MODEL_IMAGE_PRO", "gemini-9-pro-image")
    await flow_generate_image(prompt="x", model="pro")
    assert client.aio.interactions.create.call_args.kwargs["model"] == "gemini-9-pro-image"
    await flow_generate_image(prompt="x", model="flash")  # 0.1.0 alias still works
    assert client.aio.interactions.create.call_args.kwargs["model"] == config.DEFAULT_MODEL_IMAGE_FAST


async def test_video_model_env_override(client, monkeypatch):
    monkeypatch.setenv("FLOW_MODEL_VIDEO", "gemini-omni-9-flash")
    client.aio.interactions.create.return_value = _interaction("video", MP4)
    await flow_generate_video(prompt="waves", duration_seconds=3, resolution="360p")
    assert client.aio.interactions.create.call_args.kwargs["model"] == "gemini-omni-9-flash"


# ── File names + JSONL log ───────────────────────────────────────────────────


def test_slug_keeps_korean_and_strips_symbols():
    assert ledger.slug("Neon Tokyo alley, at night!!") == "neon-tokyo-alley-at-night"
    assert ledger.slug("밤의 네온 골목") == "밤의-네온-골목"
    assert ledger.slug("") == "untitled"
    assert len(ledger.slug("word " * 50)) <= 40


async def test_filename_contains_prompt_and_log_written(client, tmp_path):
    result = await flow_generate_image(prompt="Neon Tokyo alley", number_of_images=2)
    files = sorted(tmp_path.glob("*_image_neon-tokyo-alley_*.png"))
    assert len(files) == 2 and files[0].read_bytes() == PNG
    assert "2 image(s)" in result
    rows = _log(tmp_path)
    assert rows[-1]["status"] == "ok" and rows[-1]["count"] == 2
    assert rows[-1]["prompt"] == "Neon Tokyo alley"
    assert rows[-1]["est_cost_usd"] == pytest.approx(0.0672)


async def test_error_is_logged_and_raised(client, tmp_path):
    client.aio.interactions.create.return_value = SimpleNamespace(
        id="x", status="failed", output_text="blocked", steps=[])
    with pytest.raises(RuntimeError, match="No image returned"):
        await flow_generate_image(prompt="bad")
    assert _log(tmp_path)[-1]["status"] == "error"


# ── Presets ──────────────────────────────────────────────────────────────────


async def test_format_and_style_presets(client):
    await flow_generate_image(prompt="cat", preset="pinterest-pin", style="watercolor")
    kw = client.aio.interactions.create.call_args.kwargs
    assert kw["response_format"]["aspect_ratio"] == "2:3"
    assert kw["response_format"]["image_size"] == "2K"
    assert "watercolor" in kw["input"]


async def test_explicit_args_override_preset(client):
    await flow_generate_image(prompt="cat", preset="shorts", aspect_ratio="1:1")
    assert client.aio.interactions.create.call_args.kwargs["response_format"]["aspect_ratio"] == "1:1"


async def test_unknown_preset_raises(client):
    with pytest.raises(ValueError, match="Unknown preset"):
        await flow_generate_image(prompt="cat", preset="nope")


async def test_custom_presets_file(client, tmp_path, monkeypatch):
    f = tmp_path / "p.json"
    f.write_text(json.dumps({"formats": {"tpt-cover": {"aspect_ratio": "1:1", "image_size": "4K"}},
                             "styles": {"moon": "pastel moonlight"}}), encoding="utf-8")
    monkeypatch.setenv("FLOW_PRESETS_FILE", str(f))
    await flow_generate_image(prompt="book", preset="tpt-cover", style="moon")
    kw = client.aio.interactions.create.call_args.kwargs
    assert kw["response_format"]["image_size"] == "4K" and "pastel moonlight" in kw["input"]
    assert "tpt-cover" in await flow_list_presets()


# ── Edit + references ────────────────────────────────────────────────────────


async def test_edit_sends_text_and_image(client, tmp_path):
    src = _png(tmp_path)
    result = await flow_edit_image(image_path=src, prompt="a forest", edit_mode="bgswap",
                                   mask_mode="MASK_MODE_BACKGROUND")
    inp = client.aio.interactions.create.call_args.kwargs["input"]
    assert inp[0]["type"] == "text" and "background" in inp[0]["text"]
    assert inp[1]["type"] == "image" and base64.b64decode(inp[1]["data"]) == PNG
    assert "_edit_" in result


async def test_references_limits(client, tmp_path):
    paths = [_png(tmp_path, f"r{i}.png") for i in range(3)]
    result = await flow_generate_image_with_references(prompt="group", reference_image_paths=paths)
    assert len(client.aio.interactions.create.call_args.kwargs["input"]) == 4
    assert "3 reference(s)" in result
    with pytest.raises(ValueError, match="14"):
        await flow_generate_image_with_references(prompt="x", reference_image_paths=paths * 5)


# ── Video ────────────────────────────────────────────────────────────────────


async def test_video_request_shape(client, tmp_path):
    client.aio.interactions.create.return_value = _interaction("video", MP4, iid="v1_abc")
    result = await flow_generate_video(prompt="drone shot", duration_seconds=99, preset="shorts",
                                       confirm_cost=True)
    kw = client.aio.interactions.create.call_args.kwargs
    assert kw["response_format"] == {"type": "video", "aspect_ratio": "9:16", "duration": "15s",
                                     "resolution": "720p"}
    assert "v1_abc" in result and "SynthID" in result
    assert list(tmp_path.glob("*_video_drone-shot.mp4"))


async def test_video_cost_gate_blocks_until_confirmed(client, tmp_path):
    result = await flow_generate_video(prompt="sunset", duration_seconds=10)  # ~$0.70 > $0.50
    assert result.startswith("NOT GENERATED YET") and "$0.70" in result
    client.aio.interactions.create.assert_not_called()
    assert _log(tmp_path) == []


async def test_cheap_video_skips_gate(client):
    client.aio.interactions.create.return_value = _interaction("video", MP4)
    result = await flow_generate_video(prompt="sunset", duration_seconds=5)  # ~$0.35
    assert "Saved video" in result


async def test_hd_video_uses_uri_delivery(client, tmp_path):
    item = SimpleNamespace(type="video", data=None, mime_type="video/mp4",
                           uri="https://generativelanguage.googleapis.com/v1beta/files/xyz:download?alt=media")
    client.aio.interactions.create.return_value = SimpleNamespace(
        id="v1", status="completed", output_text="", steps=[SimpleNamespace(type="model_output", content=[item])])
    await flow_generate_video(prompt="hd", resolution="1080p", duration_seconds=3)
    assert client.aio.interactions.create.call_args.kwargs["response_format"]["delivery"] == "uri"
    client.aio.files.get.assert_awaited_with(name="files/xyz")
    client.aio.files.download.assert_awaited()


async def test_video_with_first_and_last_frame(client, tmp_path):
    client.aio.interactions.create.return_value = _interaction("video", MP4)
    a, b = _png(tmp_path, "a.png"), _png(tmp_path, "b.png")
    await flow_generate_video(prompt="morph", anchor_frame_path=a, last_frame_path=b,
                              duration_seconds=15, confirm_cost=True)
    kw = client.aio.interactions.create.call_args.kwargs
    assert [p["type"] for p in kw["input"]] == ["image", "image", "text"]
    assert kw["response_format"]["duration"] == "10s"  # interpolation max


async def test_bad_video_aspect_raises(client):
    with pytest.raises(ValueError, match="aspect_ratio"):
        await flow_generate_video(prompt="x", aspect_ratio="1:1")


async def test_extend_with_previous_interaction(client):
    client.aio.interactions.create.return_value = _interaction("video", MP4)
    await flow_extend_video(prompt="continue", previous_interaction_id="v1_prev", confirm_cost=True)
    kw = client.aio.interactions.create.call_args.kwargs
    assert kw["previous_interaction_id"] == "v1_prev"
    client.aio.files.upload.assert_not_called()


async def test_extend_uploads_local_video(client, tmp_path):
    client.aio.interactions.create.return_value = _interaction("video", MP4)
    vid = tmp_path / "clip.mp4"
    vid.write_bytes(MP4)
    await flow_extend_video(prompt="continue", video_path=str(vid), duration_seconds=20,
                            confirm_cost=True)
    kw = client.aio.interactions.create.call_args.kwargs
    assert kw["input"][0] == {"type": "video", "uri": "https://x/files/abc"}
    assert kw["response_format"]["duration"] == "10s"


async def test_image_to_video_pipeline(client, tmp_path):
    client.aio.interactions.create.side_effect = [_interaction("image", PNG), _interaction("video", MP4)]
    result = await flow_image_to_video(video_prompt="comes alive", image_prompt="lake at dawn",
                                       duration_seconds=4)
    assert client.aio.interactions.create.await_count == 2
    assert "Anchor image" in result and "Saved video" in result
    assert [r["kind"] for r in _log(tmp_path)] == ["image", "video"]


# ── Limits, cost, usage ──────────────────────────────────────────────────────


async def test_daily_image_limit(client, monkeypatch):
    monkeypatch.setenv("FLOW_DAILY_IMAGE_LIMIT", "3")
    await flow_generate_image(prompt="a", number_of_images=2)
    with pytest.raises(RuntimeError, match="Daily image limit"):
        await flow_generate_image(prompt="b", number_of_images=2)


async def test_daily_video_limit(client, monkeypatch):
    monkeypatch.setenv("FLOW_DAILY_VIDEO_LIMIT", "1")
    client.aio.interactions.create.return_value = _interaction("video", MP4)
    await flow_generate_video(prompt="a", duration_seconds=3)
    with pytest.raises(RuntimeError, match="Daily video limit"):
        await flow_generate_video(prompt="b", duration_seconds=3)


async def test_daily_budget(client, monkeypatch):
    monkeypatch.setenv("FLOW_DAILY_BUDGET_USD", "0.10")
    await flow_generate_image(prompt="a", number_of_images=2)  # ~$0.067
    with pytest.raises(RuntimeError, match="Daily budget"):
        await flow_generate_image(prompt="b", number_of_images=2)


async def test_usage_and_estimate(client):
    await flow_generate_image(prompt="a")
    usage = await flow_usage_today()
    assert "1 image(s)" in usage and "generation_log.jsonl" in usage
    est = await flow_estimate_cost(kind="video", duration_seconds=10, resolution="1080p")
    assert "$1.04" in est
    assert pricing.image_cost("gemini-3-pro-image", "4K", 2) == pytest.approx(0.48)


def test_placeholder_key_is_rejected(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "YOUR_GOOGLE_AI_STUDIO_KEY")
    with pytest.raises(EnvironmentError):
        server._get_client()


def test_server_object_registered_tools():
    assert server.mcp is not None
    assert presets.resolve_format("shorts")["aspect_ratio"] == "9:16"
