# Google Flow MCP

A Python MCP server that gives **Claude Desktop** direct access to Google AI's latest image and video generation models.

| Capability | Model | Tier |
|---|---|---|
| High-quality image generation & editing | **Nano Banana Pro** (`gemini-3-pro-image`) | Free |
| Fast image generation | **Nano Banana 2** (`gemini-3.1-flash-image`) | Free |
| Cinematic video with native audio | **Veo 3.1** (`veo-3.1-generate-preview`) | Paid |

## Tools

| Tool | What it does |
|---|---|
| `flow_generate_image` | Text → 1–4 images, up to 4K, choice of model |
| `flow_edit_image` | Edit an image with natural language (inpaint, outpaint, bg-swap) |
| `flow_generate_image_with_references` | Generate guided by up to 14 reference images |
| `flow_generate_video` | Text → cinematic video, optional anchor frame |
| `flow_extend_video` | Extend an existing Veo clip |
| `flow_image_to_video` | Full pipeline: Nano Banana Pro image → Veo 3.1 video |

## Prerequisites

- Python 3.10 or newer
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/) (recommended) or `pip`
- A Google AI Studio API key — get one free at [aistudio.google.com/apikey](https://aistudio.google.com/apikey)

## Installation

```bash
# Using uv (recommended — no virtual env setup needed)
uvx google-flow-mcp

# Or install with pip
pip install google-flow-mcp
```

## Claude Desktop Configuration

Add the following to your Claude Desktop config file:

```json
{
  "mcpServers": {
    "google-flow": {
      "command": "uvx",
      "args": ["google-flow-mcp"],
      "env": {
        "GOOGLE_API_KEY": "YOUR_GOOGLE_AI_STUDIO_KEY"
      }
    }
  }
}
```

### Config file locations

| Platform | Path |
|---|---|
| **Windows Store** | `%LOCALAPPDATA%\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude_desktop_config.json` |
| **Windows Direct** | `%APPDATA%\Claude\claude_desktop_config.json` |
| **macOS** | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| **Linux** | `~/.config/Claude/claude_desktop_config.json` |

After editing the config, **restart Claude Desktop**.

## Output Directory

Generated files are saved to `~/google_flow_outputs/` by default.

Override with the `FLOW_OUTPUT_DIR` environment variable:

```json
"env": {
  "GOOGLE_API_KEY": "YOUR_KEY",
  "FLOW_OUTPUT_DIR": "/Users/you/Pictures/ai-outputs"
}
```

## Usage Examples

Once connected, ask Claude naturally:

- *"Generate a photo-realistic image of a neon-lit Tokyo alley at night"*
- *"Edit this image to remove the background and replace it with a forest"*
- *"Generate a video of a rocket launching from a desert at dusk with dramatic audio"*
- *"Create an anchor image of ocean waves, then animate it into a video"*

## Important Notes

- **Image generation** (Nano Banana Pro / Nano Banana 2) works on the **free tier**.
- **Video generation** (Veo 3.1) requires a **paid Google AI API plan**.
- All Veo videos are **SynthID-watermarked** by Google.
- Generated videos are stored on Google's servers for **2 days** after creation.
- Video generation typically takes **1–4 minutes** — Claude will wait automatically.

## Development

```bash
git clone https://github.com/joshuadaniel-8090/google-flow-mcp
cd google-flow-mcp
pip install -e ".[dev]"
pytest -v
```

## License

Apache 2.0 — see [LICENSE](LICENSE).
