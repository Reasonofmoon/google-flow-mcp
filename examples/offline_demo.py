"""Run the whole studio workflow in demo mode: no API key, no network, nothing billed.

    python examples/offline_demo.py [output_dir]

It calls the same tool functions an MCP client would call and leaves a project folder with
placeholder keyframes, clips, audio, an assembled film and board.html.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "demo_output").resolve()
OUT.mkdir(parents=True, exist_ok=True)
os.environ["FLOW_DEMO"] = "1"
os.environ["FLOW_OUTPUT_DIR"] = str(OUT)

from google_flow_mcp import studio  # noqa: E402

SHOTS = [
    {"prompt": "@mira folds a big paper rocket at her desk by a rainy window", "action": "she smooths the last fold",
     "camera": "push-in", "duration": 4, "sound": "soft rain, paper rustle"},
    {"prompt": "@mira carries the paper rocket up to the rooftop at dusk", "action": "wind lifts her yellow raincoat",
     "camera": "tracking", "duration": 4, "sound": "wind, distant city"},
    {"prompt": "The paper rocket on the rooftop edge, pointing at a huge full moon", "action": "its tip starts to glow",
     "camera": "tilt-up", "duration": 4, "sound": "low hum rising"},
    {"prompt": "@mira watches the paper rocket fly toward the moon", "action": "a thin trail of light follows it",
     "camera": "crane-up", "duration": 5, "dialogue": 'Mira whispers: "Go on."', "sound": "soft whoosh"},
]


def show(result, preview_name: str | None = None) -> None:
    """Print the tool's text; save its preview image (what the assistant would see)."""
    if isinstance(result, str):
        print(result, "\n")
        return
    print(result[0], "\n")
    if preview_name and len(result) > 1:
        (OUT / preview_name).write_bytes(result[1].data)


async def main() -> None:
    show(await studio.flow_project(name="paper-rocket", title="The Paper Rocket", aspect_ratio="16:9",
                                   logline="A girl folds a paper rocket and sends it to the moon.",
                                   style="warm watercolor picture book"))
    show(await studio.flow_ingredient_save(
        name="mira", description="an 8-year-old girl with short silver hair and a yellow raincoat", generate=True),
        "preview_ingredient.jpg")
    show(await studio.flow_storyboard_plan(shots=SHOTS))
    show(await studio.flow_storyboard_keyframes(), "preview_keyframes.jpg")
    show(await studio.flow_storyboard_render(quality="draft", wait_seconds=600), "preview_render.jpg")
    show(await studio.flow_edit_video(prompt="Add light snowfall", shot=4))
    show(await studio.flow_generate_music(prompt="warm lo-fi piano, hopeful, 80 bpm"))
    show(await studio.flow_generate_narration(
        text="One rainy evening, Mira folded a rocket out of paper. And then she let it go.",
        voice="Sulafat", style="gentle storyteller"))
    show(await studio.flow_assemble(), "preview_film.jpg")
    show(await studio.flow_board())
    show(await studio.flow_project())


if __name__ == "__main__":
    asyncio.run(main())
