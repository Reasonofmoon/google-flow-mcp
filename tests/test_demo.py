"""Demo mode: the whole workflow with no API key, no mocks, and no spend."""

from __future__ import annotations

import json

import google_flow_mcp.server as server
from google_flow_mcp import demo, media, project
from google_flow_mcp.server import flow_generate_image, flow_usage_today
from google_flow_mcp.studio import (
    flow_assemble,
    flow_generate_music,
    flow_generate_narration,
    flow_ingredient_save,
    flow_project,
    flow_storyboard_keyframes,
    flow_storyboard_plan,
    flow_storyboard_render,
)

from .conftest import text_of


def test_card_handles_any_language():
    img = demo.card("달나라로 가는 종이 로켓 🚀", (480, 854), "image")
    assert img.size == (480, 854)
    assert demo.tone(0.5)[:4] == b"RIFF"


async def test_demo_mode_runs_whole_workflow_without_key(tmp_path, monkeypatch):
    monkeypatch.setenv("FLOW_DEMO", "1")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    quick = await flow_generate_image(prompt="a lighthouse at dawn", preset="pinterest-pin")
    assert "DEMO MODE" in text_of(quick) and isinstance(quick, list)
    assert isinstance(server.get_client(), demo.DemoClient)

    await flow_project(name="demo film", aspect_ratio="9:16")
    await flow_ingredient_save(name="mira", description="a girl in a yellow raincoat", generate=True)
    await flow_storyboard_plan(shots=[
        {"prompt": "@mira on a rooftop", "camera": "orbit", "duration": 5},
        {"prompt": "a paper rocket under the moon", "duration": 5},
    ])
    await flow_storyboard_keyframes()
    # 10 s at 720p would be ~$0.70, above the confirm threshold; demo mode must not stop to ask.
    rendered = text_of(await flow_storyboard_render(quality="standard", wait_seconds=300))
    assert "NOT GENERATED YET" not in rendered and "FAILED" not in rendered and "DEMO MODE" in rendered
    await flow_generate_music(prompt="soft piano")
    await flow_generate_narration(text="Hello there, this is a demo narration.")
    assert "Film assembled: 2 shot(s)" in text_of(await flow_assemble())

    p = project.load()
    info = await media.probe(p["films"][-1]["path"])
    assert 9 < info["duration"] < 11 and info["height"] > info["width"] and info["has_audio"]
    assert p["spent_usd"] == 0
    rows = [json.loads(line) for line in (tmp_path / "generation_log.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) >= 8 and all(r["demo"] and r["est_cost_usd"] == 0 and r["status"] == "ok" for r in rows)
    usage = await flow_usage_today()
    assert "~$0.00" in usage and "DEMO MODE" in usage
