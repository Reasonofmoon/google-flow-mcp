"""Core generation tools: models, file names, log, presets, video, limits."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import google_flow_mcp.server as server
from google_flow_mcp import config, ledger, presets, pricing
from google_flow_mcp.server import (
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

from .conftest import FAKE_MP4, PNG, interaction, text_of, write_png


def _log(tmp_path: Path) -> list[dict]:
    p = tmp_path / "generation_log.jsonl"
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


# ── Models from env ──────────────────────────────────────────────────────────


async def test_default_image_model_is_fast(client):
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
    client.aio.interactions.create.return_value = interaction("video", FAKE_MP4)
    await flow_generate_video(prompt="waves", duration_seconds=3, resolution="360p")
    assert client.aio.interactions.create.call_args.kwargs["model"] == "gemini-omni-9-flash"


# ── File names, log, previews ────────────────────────────────────────────────


def test_slug_keeps_korean_and_strips_symbols():
    assert ledger.slug("Neon Tokyo alley, at night!!") == "neon-tokyo-alley-at-night"
    assert ledger.slug("밤의 네온 골목") == "밤의-네온-골목"
    assert ledger.slug("") == "untitled"
    assert len(ledger.slug("word " * 50)) <= 40


async def test_filename_log_and_inline_preview(client, tmp_path):
    result = await flow_generate_image(prompt="Neon Tokyo alley", number_of_images=2)
    files = sorted(tmp_path.glob("*_image_neon-tokyo-alley_*.png"))
    assert len(files) == 2 and files[0].read_bytes() == PNG
    assert isinstance(result, list) and len(result) == 2  # text + one contact sheet
    assert "2 image(s)" in text_of(result)
    rows = _log(tmp_path)
    assert rows[-1]["status"] == "ok" and rows[-1]["count"] == 2
    assert rows[-1]["est_cost_usd"] == pytest.approx(0.0672)


async def test_preview_can_be_turned_off(client, monkeypatch):
    monkeypatch.setenv("FLOW_INLINE_PREVIEW", "0")
    assert isinstance(await flow_generate_image(prompt="plain"), str)


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
    listing = await flow_list_presets()
    assert "tpt-cover" in listing and "push-in" in listing and "ffmpeg: found" in listing


# ── Edit + references ────────────────────────────────────────────────────────


async def test_edit_sends_text_and_image(client, tmp_path):
    src = write_png(tmp_path)
    result = await flow_edit_image(image_path=src, prompt="a forest", edit_mode="bgswap",
                                   mask_mode="MASK_MODE_BACKGROUND")
    inp = client.aio.interactions.create.call_args.kwargs["input"]
    assert inp[0]["type"] == "text" and "background" in inp[0]["text"]
    assert inp[1]["type"] == "image" and base64.b64decode(inp[1]["data"]) == Path(src).read_bytes()
    assert "_edit_" in text_of(result)


async def test_references_limits(client, tmp_path):
    paths = [write_png(tmp_path, f"r{i}.png") for i in range(3)]
    result = await flow_generate_image_with_references(prompt="group", reference_image_paths=paths)
    assert len(client.aio.interactions.create.call_args.kwargs["input"]) == 4
    assert "3 reference(s)" in text_of(result)
    with pytest.raises(ValueError, match="14"):
        await flow_generate_image_with_references(prompt="x", reference_image_paths=paths * 5)


# ── Video ────────────────────────────────────────────────────────────────────


async def test_video_request_shape_and_camera(client, tmp_path):
    client.aio.interactions.create.return_value = interaction("video", FAKE_MP4, iid="v1_abc")
    result = await flow_generate_video(prompt="drone shot", duration_seconds=99, preset="shorts",
                                       camera="orbit", confirm_cost=True)
    kw = client.aio.interactions.create.call_args.kwargs
    assert kw["response_format"] == {"type": "video", "aspect_ratio": "9:16", "duration": "15s",
                                     "resolution": "720p"}
    assert presets.CAMERA["orbit"] in kw["input"]
    assert "v1_abc" in result and "SynthID" in result
    assert list(tmp_path.glob("*_video_drone-shot.mp4"))


async def test_video_cost_gate_blocks_until_confirmed(client, tmp_path):
    result = await flow_generate_video(prompt="sunset", duration_seconds=10)  # ~$0.70 > $0.50
    assert result.startswith("NOT GENERATED YET") and "$0.70" in result
    client.aio.interactions.create.assert_not_called()
    assert _log(tmp_path) == []


async def test_cheap_video_skips_gate(client):
    client.aio.interactions.create.return_value = interaction("video", FAKE_MP4)
    assert "Saved video" in await flow_generate_video(prompt="sunset", duration_seconds=5)  # ~$0.35


async def test_hd_video_uses_uri_delivery(client):
    item = SimpleNamespace(type="video", data=None, mime_type="video/mp4",
                           uri="https://generativelanguage.googleapis.com/v1beta/files/xyz:download?alt=media")
    client.aio.interactions.create.return_value = SimpleNamespace(
        id="v1", status="completed", output_text="", steps=[SimpleNamespace(type="model_output", content=[item])])
    await flow_generate_video(prompt="hd", resolution="1080p", duration_seconds=3)
    assert client.aio.interactions.create.call_args.kwargs["response_format"]["delivery"] == "uri"
    client.aio.files.get.assert_awaited_with(name="files/xyz")
    client.aio.files.download.assert_awaited()


async def test_video_with_first_and_last_frame(client, tmp_path):
    client.aio.interactions.create.return_value = interaction("video", FAKE_MP4)
    a, b = write_png(tmp_path, "a.png"), write_png(tmp_path, "b.png")
    await flow_generate_video(prompt="morph", anchor_frame_path=a, last_frame_path=b,
                              duration_seconds=15, confirm_cost=True)
    kw = client.aio.interactions.create.call_args.kwargs
    assert [p["type"] for p in kw["input"]] == ["image", "image", "text"]
    assert kw["response_format"]["duration"] == "10s"  # interpolation max


async def test_bad_video_aspect_raises(client):
    with pytest.raises(ValueError, match="aspect_ratio"):
        await flow_generate_video(prompt="x", aspect_ratio="1:1")


async def test_extend_with_previous_interaction(client):
    client.aio.interactions.create.return_value = interaction("video", FAKE_MP4)
    await flow_extend_video(prompt="continue", previous_interaction_id="v1_prev", confirm_cost=True)
    assert client.aio.interactions.create.call_args.kwargs["previous_interaction_id"] == "v1_prev"
    client.aio.files.upload.assert_not_called()


async def test_extend_uploads_local_video(client, tmp_path):
    client.aio.interactions.create.return_value = interaction("video", FAKE_MP4)
    vid = tmp_path / "clip.mp4"
    vid.write_bytes(FAKE_MP4)
    await flow_extend_video(prompt="continue", video_path=str(vid), duration_seconds=20, confirm_cost=True)
    kw = client.aio.interactions.create.call_args.kwargs
    assert kw["input"][0] == {"type": "video", "uri": "https://x/files/abc"}
    assert kw["response_format"]["duration"] == "10s"


async def test_image_to_video_pipeline(client, tmp_path):
    client.aio.interactions.create.side_effect = [interaction("image", PNG), interaction("video", FAKE_MP4)]
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
    client.aio.interactions.create.return_value = interaction("video", FAKE_MP4)
    await flow_generate_video(prompt="a", duration_seconds=3)
    with pytest.raises(RuntimeError, match="Daily video limit"):
        await flow_generate_video(prompt="b", duration_seconds=3)


async def test_daily_budget_default_and_override(client, monkeypatch):
    assert config.daily_budget_usd() == 5.0
    monkeypatch.setenv("FLOW_DAILY_BUDGET_USD", "0.10")
    await flow_generate_image(prompt="a", number_of_images=2)  # ~$0.067
    with pytest.raises(RuntimeError, match="Daily budget"):
        await flow_generate_image(prompt="b", number_of_images=2)


async def test_usage_and_estimate(client):
    await flow_generate_image(prompt="a")
    usage = await flow_usage_today()
    assert "1 image(s)" in usage and "generation_log.jsonl" in usage
    assert "$1.04" in await flow_estimate_cost(kind="video", duration_seconds=10, resolution="1080p")
    assert pricing.image_cost("gemini-3-pro-image", "4K", 2) == pytest.approx(0.48)
    assert pricing.music_cost("lyria-3-clip-preview") == 0.04


def test_client_uses_v1beta_where_video_music_and_tts_models_live(monkeypatch, mocker):
    """Found by the first live call: the SDK default 'v1' answers 404 for gemini-omni-1.2-flash."""
    made = mocker.patch.object(server.genai, "Client")
    monkeypatch.setenv("GOOGLE_API_KEY", "real-looking-key")
    server._get_client()
    assert made.call_args.kwargs["http_options"] == {"api_version": "v1beta"}
    monkeypatch.setenv("FLOW_API_VERSION", "v1alpha")
    server._get_client()
    assert made.call_args.kwargs["http_options"] == {"api_version": "v1alpha"}


def test_model_not_found_error_gets_a_hint():
    text = server._explain(Exception("Error code: 404 - Model 'gemini-omni-1.2-flash' not found."))
    assert "FLOW_MODEL_" in text and "v1beta" in text
    assert "billing enabled" in server._explain(RuntimeError("402 prepayment credits are depleted"))


def test_placeholder_key_is_rejected(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "YOUR_GOOGLE_AI_STUDIO_KEY")
    with pytest.raises(EnvironmentError):
        server._get_client()
