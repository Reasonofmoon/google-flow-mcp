"""Studio tools: project, ingredients, storyboard, background renders, audio, assembly, review.

ffmpeg really joins and mixes the clips here; only the Google API is mocked.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from google_flow_mcp import board, config, media, presets, project, studio
from google_flow_mcp.server import flow_generate_image, flow_generate_video
from google_flow_mcp.studio import (
    flow_assemble,
    flow_board,
    flow_edit_video,
    flow_generate_music,
    flow_generate_narration,
    flow_ingredient_save,
    flow_project,
    flow_review,
    flow_shot_update,
    flow_storyboard_keyframes,
    flow_storyboard_plan,
    flow_storyboard_render,
)

from .conftest import interaction, text_of, write_png

SHOTS = [
    {"prompt": "@mira looks up at the full moon from a rooftop", "camera": "push-in", "duration": 3,
     "sound": "quiet night wind"},
    {"prompt": "A small rocket on a launch pad at dawn", "action": "smoke starts to rise", "duration": 4},
]


async def _setup(tmp_path, with_image: bool = True) -> None:
    await flow_project(name="Moon Trip", aspect_ratio="16:9", style="soft watercolor")
    await flow_ingredient_save(name="Mira", description="a girl with short silver hair and a yellow raincoat",
                               image_paths=[write_png(tmp_path, "mira.png")] if with_image else None)
    await flow_storyboard_plan(shots=SHOTS)


def _calls(client, model_part: str) -> list[dict]:
    return [c.kwargs for c in client.aio.interactions.create.call_args_list if model_part in c.kwargs["model"]]


# ── media (real ffmpeg) ──────────────────────────────────────────────────────


async def test_probe_and_review_sheet(clips):
    info = await media.probe(clips["sound"])
    assert info["has_video"] and info["has_audio"] and (info["width"], info["height"]) == (320, 180)
    assert 0.8 < info["duration"] < 1.3
    assert not (await media.probe(clips["silent"]))["has_audio"]
    sheet, _ = await media.video_sheet(clips["sound"], frames=4)
    assert sheet[:2] == b"\xff\xd8"  # JPEG


async def test_concat_trims_and_fills_silence(clips, tmp_path):
    out = tmp_path / "joined.mp4"
    await media.concat([{"path": clips["sound"], "start": 0, "end": 0.5}, {"path": clips["silent"]}], out)
    info = await media.probe(out)
    assert info["has_audio"] and 1.3 < info["duration"] < 1.8


def test_contact_sheet_with_missing_cell(tmp_path):
    good = write_png(tmp_path, "a.png")
    assert media.contact_sheet([("S1", good), ("S2", None)])[:2] == b"\xff\xd8"
    assert media.safe_thumbnail(tmp_path / "missing.png") is None


# ── project + ingredients ────────────────────────────────────────────────────


async def test_project_create_open_and_status(client, tmp_path):
    assert "No active project" in await flow_project()
    out = await flow_project(name="Moon Trip", aspect_ratio="9:16", logline="A girl goes to the moon")
    assert "moon-trip" in out and "9:16" in out and "flow_storyboard_plan" in out
    assert project.active_name() == "moon-trip"
    assert (project.dir_of("Moon Trip") / "board.html").exists()
    with pytest.raises(ValueError, match="aspect_ratio"):
        await flow_project(name="bad", aspect_ratio="1:1")


async def test_ingredient_tag_attaches_reference_everywhere(client, tmp_path):
    await _setup(tmp_path)
    await flow_generate_image(prompt="@mira waving, portrait")
    kw = client.aio.interactions.create.call_args.kwargs
    assert isinstance(kw["input"], list) and kw["input"][1]["type"] == "image"
    assert "Mira waving" in kw["input"][0]["text"] and "image 1: Mira (character)" in kw["input"][0]["text"]

    client.aio.interactions.create.return_value = interaction("video", b"\x00" * 64)
    await flow_generate_video(prompt="@mira runs on the beach", duration_seconds=3, resolution="360p")
    kw = client.aio.interactions.create.call_args.kwargs
    assert [p["type"] for p in kw["input"]] == ["image", "text"]


async def test_unknown_tag_stays_plain_text(client):
    await flow_generate_image(prompt="contact me @home")
    assert client.aio.interactions.create.call_args.kwargs["input"] == "contact me @home"


async def test_ingredient_generate_makes_reference_sheet(client, tmp_path):
    await flow_project(name="p1")
    result = await flow_ingredient_save(name="Robo", description="a small blue robot", kind="object", generate=True)
    assert "Generated a reference sheet" in text_of(result) and isinstance(result, list)
    item = project.load()["ingredients"]["robo"]
    assert len(item["images"]) == 1 and Path(item["images"][0]).exists()
    assert "three-quarter" in client.aio.interactions.create.call_args.kwargs["input"]


# ── storyboard ───────────────────────────────────────────────────────────────


async def test_plan_reports_costs_and_guards_replace(studio_client, tmp_path):
    await flow_project(name="plan")
    with pytest.raises(ValueError, match="not saved"):
        await flow_storyboard_plan(shots=[{"prompt": "x", "ingredients": ["ghost"]}])
    out = await flow_storyboard_plan(shots=SHOTS)
    assert "2 shot(s), 7s" in out and "draft render (360p) ~$0.16" in out and "@mira not saved" in out
    await flow_storyboard_keyframes()
    with pytest.raises(ValueError, match="already has keyframes"):
        await flow_storyboard_plan(shots=SHOTS)
    assert "3 shot(s)" in await flow_storyboard_plan(shots=[{"prompt": "The end card"}], mode="append")


async def test_keyframes_use_ingredients_and_return_sheet(studio_client, tmp_path):
    await _setup(tmp_path)
    result = await flow_storyboard_keyframes()
    assert isinstance(result, list) and "2/2 generated" in text_of(result)
    calls = _calls(studio_client, "nano-banana")
    assert len(calls) == 2 and all(k["response_format"]["aspect_ratio"] == "16:9" for k in calls)
    tagged = next(k for k in calls if isinstance(k["input"], list))  # shot 1 uses @mira
    assert "soft watercolor" in tagged["input"][0]["text"] and tagged["input"][1]["type"] == "image"
    p = project.load()
    assert all(s["status"] == "keyframed" and Path(s["keyframe"]).exists() for s in p["shots"])
    assert "already have keyframes" in text_of(await flow_storyboard_keyframes())


async def test_shot_update_clears_keyframe_and_sets_trim(studio_client, tmp_path):
    await _setup(tmp_path)
    await flow_storyboard_keyframes()
    out = await flow_shot_update(shot=2, prompt="A tall rocket at night", trim_end=0.5)
    assert "keyframe cleared" in out
    s = project.get_shot(project.load(), 2)
    assert s["keyframe"] is None and s["trim"] == [None, 0.5] and s["status"] == "planned"
    with pytest.raises(ValueError, match="take"):
        await flow_shot_update(shot=2, select_take=1)


async def test_render_uses_keyframe_first_and_draft_resolution(studio_client, tmp_path):
    await _setup(tmp_path)
    await flow_storyboard_keyframes()
    result = await flow_storyboard_render(quality="draft", wait_seconds=60)
    text = text_of(result)
    assert "still rendering" not in text and "FAILED" not in text
    assert isinstance(result, list)  # mid-frame sheet made by ffmpeg
    video = sorted(_calls(studio_client, "omni"), key=lambda k: k["response_format"]["duration"])[0]
    assert video["response_format"] == {"type": "video", "aspect_ratio": "16:9", "duration": "3s", "resolution": "360p"}
    kinds = [part["type"] for part in video["input"]]
    assert kinds == ["image", "image", "text"]  # keyframe, Mira reference, prompt
    prompt = video["input"][-1]["text"]
    assert prompt.startswith("Start exactly from the first attached image")
    assert presets.CAMERA["push-in"] in prompt and "image 2: Mira" in prompt and "quiet night wind" in prompt
    p = project.load()
    assert all(s["status"] == "rendered" and len(s["takes"]) == 1 for s in p["shots"])
    assert p["spent_usd"] > 0
    assert "Nothing to start" in await flow_storyboard_render(quality="draft")


async def test_render_cost_gate(studio_client, tmp_path):
    await flow_project(name="big")
    await flow_storyboard_plan(shots=[{"prompt": f"shot {i}", "duration": 10} for i in range(4)])
    out = await flow_storyboard_render(quality="standard")  # 40 s x $0.07 = $2.80
    assert out.startswith("NOT GENERATED YET") and "$2.80" in out
    assert _calls(studio_client, "omni") == []


async def test_slow_render_continues_in_background(studio_client, clips, tmp_path):
    async def slow(**kw):
        if "omni" in kw["model"]:
            await asyncio.sleep(2.5)
            return interaction("video", clips["bytes"])
        return interaction("image", b"")

    studio_client.aio.interactions.create.side_effect = slow
    await flow_project(name="slow")
    await flow_storyboard_plan(shots=[{"prompt": "one slow shot", "duration": 3}])
    text = text_of(await flow_storyboard_render(wait_seconds=1))
    assert "still rendering in the background" in text
    assert "[rendering]" in await flow_project()
    assert "already rendering" in await flow_storyboard_render()
    await asyncio.gather(*[t for (name, _), t in studio._jobs.items() if name == "slow"])
    assert project.get_shot(project.load(), 1)["status"] == "rendered"


async def test_failed_shot_is_recorded(studio_client, tmp_path):
    async def boom(**kw):
        raise RuntimeError("quota exceeded")

    await flow_project(name="fail")
    await flow_storyboard_plan(shots=[{"prompt": "doomed", "duration": 3}])
    studio_client.aio.interactions.create.side_effect = boom
    text = text_of(await flow_storyboard_render(wait_seconds=30))
    assert "FAILED" in text and "quota exceeded" in text
    s = project.get_shot(project.load(), 1)
    assert s["status"] == "error" and "quota exceeded" in s["error"]


# ── edit, audio, assemble, review, board ─────────────────────────────────────


async def test_full_film_pipeline(studio_client, tmp_path):
    await _setup(tmp_path)
    await flow_storyboard_keyframes()
    await flow_storyboard_render(quality="draft", wait_seconds=60)

    edited = await flow_edit_video(prompt="Add light snowfall", shot=1)
    assert "take 2 is now selected" in edited
    edit_call = _calls(studio_client, "omni")[-1]
    assert edit_call["previous_interaction_id"].startswith("v1_")
    assert edit_call["input"].endswith("Keep everything else the same.")
    assert edit_call["response_format"]["aspect_ratio"] == "16:9"  # the project's shape is kept

    music = await flow_generate_music(prompt="warm lo-fi piano")
    assert "Attached to project" in music
    assert _calls(studio_client, "lyria")[0]["input"].endswith("Instrumental only, no vocals.")
    narration = await flow_generate_narration(text="Once upon a time, a girl looked at the moon.",
                                              voice="Puck", style="calm storyteller")
    tts = _calls(studio_client, "tts")[0]
    assert tts["generation_config"] == {"speech_config": [{"voice": "Puck"}]}
    assert tts["input"][0]["content"][0]["annotations"][0]["style"] == "calm storyteller"
    assert "about 1.0s" in narration

    await flow_shot_update(shot=2, trim_end=0.5)
    result = await flow_assemble()
    text = text_of(result)
    assert "Film assembled: 2 shot(s)" in text and "with music" in text and "with narration" in text
    assert isinstance(result, list)
    p = project.load()
    film = Path(p["films"][-1]["path"])
    info = await media.probe(film)
    assert film.exists() and info["has_audio"] and 1.3 < info["duration"] < 1.8  # 1 s + trimmed 0.5 s

    review = await flow_review(str(film), frames=4)
    assert isinstance(review, list) and "audio yes" in review[0]
    image_review = await flow_review(p["shots"][0]["keyframe"])
    assert "320x180" in image_review[0]

    out = await flow_board()
    html = (project.dir_of(p["name"]) / "board.html").read_text(encoding="utf-8")
    assert "board.html" in out
    assert "Latest film" in html and "<video" in html and "@mira" in html and "<audio" in html
    assert board.render(p).count("class='card'") >= 5
    status = await flow_project()
    assert "Films: 1" in status and "takes 1:draft, 2:edit (using 2)" in status


async def test_assemble_needs_takes(studio_client, tmp_path):
    await _setup(tmp_path)
    with pytest.raises(ValueError, match="no rendered take"):
        await flow_assemble()


async def test_audio_without_project_goes_to_output_folder(studio_client, tmp_path):
    out = await flow_generate_music(prompt="epic drums", kind="song", instrumental=False)
    assert config.DEFAULT_MODEL_MUSIC_SONG in out and "Attached" not in out
    assert list(tmp_path.glob("*_music_epic-drums.wav"))
    with pytest.raises(ValueError, match="empty"):
        await flow_generate_narration(text="   ")


async def test_edit_video_needs_exactly_one_source(studio_client):
    with pytest.raises(ValueError, match="exactly one"):
        await flow_edit_video(prompt="x")
    with pytest.raises(ValueError, match="exactly one"):
        await flow_edit_video(prompt="x", video_path="a.mp4", previous_interaction_id="v1")
