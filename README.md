# Google Flow MCP

> **Reasonofmoon fork.** Based on [google-flow-mcp 0.1.0](https://pypi.org/project/google-flow-mcp/) by joshua-daniel-8090 (Apache-2.0).
> 관리 방법은 [FORK.md](FORK.md), 바뀐 점은 [CHANGELOG.md](CHANGELOG.md)를 보세요.

A Python MCP server that gives **Claude Desktop** Google's current image and video generation models,
with cost guards, presets and a generation log.

| Capability | Default model | List price (paid tier, checked 2026-11-13) |
|---|---|---|
| Fast image generation & editing | Nano Banana 2.1 (`gemini-nano-banana-2.1`) | ~$0.034 (1K) / $0.050 (2K) / $0.113 (4K) per image |
| Best quality, text-heavy layouts | Nano Banana Pro (`gemini-3-pro-image`) | ~$0.134 (1K/2K) / $0.24 (4K) per image |
| Cheapest drafts | Nano Banana 2 Lite (`gemini-3.1-flash-lite-image`) | ~$0.034 per 1K image |
| Video with native audio, 3–15 s | Gemini Omni Flash (`gemini-omni-1.2-flash`) | ~$0.023/s (360p), $0.07/s (720p), $0.104/s (1080p), $0.209/s (4K) |

**No free tier.** Every model above is "Not available" on the free tier, so the API key needs billing.
Veo 3.1 Preview, used by 0.1.0, was shut down on 2026-10-22.

## Tools

| Tool | What it does |
|---|---|
| `flow_generate_image` | Text → 1–4 images, presets and styles, up to 4K |
| `flow_edit_image` | Edit an image with plain language (add, remove, extend canvas, swap background) |
| `flow_generate_image_with_references` | Generate guided by up to 14 reference images |
| `flow_generate_video` | Text (+ optional first/last frame, up to 6 reference images) → video with audio |
| `flow_extend_video` | Continue or edit a clip (by `previous_interaction_id` or a local MP4) |
| `flow_image_to_video` | Pipeline: anchor image → animated video |
| `flow_list_presets` | Show format/style presets, active models and limits |
| `flow_estimate_cost` | Price a request without generating |
| `flow_usage_today` | Today's count and estimated spend from the log |

## Presets

`preset=` (format): `square`, `youtube-thumbnail` (16:9), `shorts` (9:16), `pinterest-pin` (2:3),
`instagram-post` (4:5), `worksheet` (3:4), `banner` (21:9).

`style=`: `photo`, `flat-illustration`, `watercolor`, `kids-book`, `3d-clay`, `infographic`, `cinematic`.

Add your own with a JSON file and `FLOW_PRESETS_FILE`:

```json
{
  "formats": {"tpt-cover": {"aspect_ratio": "1:1", "image_size": "2K", "note": "TPT cover"}},
  "styles": {"moonlight": "soft pastel watercolor, warm lighting, children's book style"}
}
```

## Settings (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `GOOGLE_API_KEY` | — | Paid Gemini API key (required) |
| `FLOW_OUTPUT_DIR` | `~/google_flow_outputs` | Where files and the log go |
| `FLOW_DEFAULT_IMAGE_MODEL` | `fast` | `fast`, `pro`, `lite` or a full model id |
| `FLOW_MODEL_IMAGE_FAST` / `_PRO` / `_LITE` | see table above | Swap in a newer model without code changes |
| `FLOW_MODEL_VIDEO` | `gemini-omni-1.2-flash` | Video model |
| `FLOW_DAILY_IMAGE_LIMIT` | `50` | Images per day, `0` = no limit |
| `FLOW_DAILY_VIDEO_LIMIT` | `5` | Video generations per day, `0` = no limit |
| `FLOW_DAILY_BUDGET_USD` | `0` (off) | Max estimated spend per day |
| `FLOW_VIDEO_CONFIRM_USD` | `0.5` | Videos estimated above this return a quote first; call again with `confirm_cost=true` |
| `FLOW_PRESETS_FILE` | — | Extra presets (JSON) |
| `FLOW_PRICES_FILE` | — | Price table overrides (JSON: `{"image": {...}, "video": {...}}`) |
| `FLOW_LOG_FILE` | `<output>/generation_log.jsonl` | Generation log path |

Limits and spend are counted from the local log, so they are estimates, not Google's billing.

## Output

Files are named `<YYYYMMDD_HHMMSS>_<kind>_<prompt-summary>[_n].<ext>`, e.g.
`20261113_091500_image_neon-tokyo-alley_0.png`. Every call (success or error) appends one JSON line to
`generation_log.jsonl`: time, tool, model, prompt, parameters, output paths, estimated cost, seconds,
and the `interaction_id` you can use to continue a video.

## Claude Desktop configuration

Run this fork from a local checkout:

```json
{
  "mcpServers": {
    "google-flow-dev": {
      "command": "uv",
      "args": ["--directory", "C:\\path\\to\\google-flow-mcp", "run", "google-flow-mcp"],
      "env": {
        "GOOGLE_API_KEY": "YOUR_PAID_GEMINI_API_KEY",
        "FLOW_OUTPUT_DIR": "C:/Users/you/Pictures/google-flow"
      }
    }
  }
}
```

Config file: `%APPDATA%\Claude\claude_desktop_config.json` (Windows),
`~/Library/Application Support/Claude/claude_desktop_config.json` (macOS),
`~/.config/Claude/claude_desktop_config.json` (Linux). Restart Claude Desktop after editing.

## Usage examples

- "Make a Pinterest pin in watercolor style: a cozy reading nook with the text 'Read More'"
- "Generate a YouTube thumbnail with the pro model, 4K, big bold title 'AI in 5 minutes'"
- "Remove the person on the left from C:/pics/beach.png"
- "How much would a 10-second 1080p video cost?"
- "Make an 8-second Shorts video of a paper airplane flying through a library, single continuous shot"
- "Continue that video: the airplane lands on a desk"

## Notes

- Generated videos carry an invisible SynthID watermark.
- Inline video data is limited to about 4 MB, so 1080p/4K use URI delivery and are downloaded automatically.
- Video extension: 3–10 s per turn, up to 30 s total; uploaded clips must be 15 s or less.
- English prompts are fully supported; other languages work but are not officially evaluated.

## Development

```bash
pip install -e ".[dev]"
pytest -v
```

CI runs the tests on Python 3.11–3.13 against both `mcp` 1.x and 2.x. All Google API calls are mocked.

## License

Apache 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
