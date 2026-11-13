"""End-to-end check of an installed google-flow-mcp, the way a desktop client uses it.

    python examples/mcp_smoke_test.py [output_dir]

Starts the real stdio server (`python -m google_flow_mcp`), speaks MCP JSON-RPC to it and runs
a whole film in demo mode: project, ingredient, storyboard, keyframes, background render, edit,
music, narration, assembly, review, board. Then it starts the server again without a key to check
that the error tells you what to do. No API key is used and nothing is billed.
"""

from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
import tempfile
import threading
import time

OUT = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else tempfile.mkdtemp(prefix="flow_smoke_")
os.makedirs(OUT, exist_ok=True)
results: list[bool] = []


def check(name: str, ok: bool, detail: object = "") -> None:
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f" | {str(detail)[:200]}" if detail != "" else ""), flush=True)


class Client:
    """A minimal MCP client: newline-delimited JSON-RPC over the server's stdin/stdout."""

    def __init__(self, extra_env: dict, label: str) -> None:
        env = {k: v for k, v in os.environ.items() if k not in ("GOOGLE_API_KEY", "GEMINI_API_KEY", "FLOW_DEMO")}
        env.update({"FLOW_OUTPUT_DIR": OUT, "PYTHONUNBUFFERED": "1", **extra_env})
        self.err = open(os.path.join(OUT, f"server-{label}.log"), "w", encoding="utf-8")
        self.started = time.time()
        self.proc = subprocess.Popen([sys.executable, "-m", "google_flow_mcp"], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=self.err, text=True, encoding="utf-8", env=env)
        self.next_id = 0
        self.guard = threading.Timer(600, self.proc.kill)
        self.guard.start()

    def rpc(self, method: str, params: dict | None = None) -> dict:
        self.next_id += 1
        msg: dict = {"jsonrpc": "2.0", "id": self.next_id, "method": method}
        if params is not None:
            msg["params"] = params
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError(f"server closed the pipe; see {self.err.name}")
            if line.lstrip().startswith("{"):
                data = json.loads(line)
                if data.get("id") == self.next_id:
                    return data

    def start(self) -> dict:
        info = self.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                       "clientInfo": {"name": "mcp-smoke-test", "version": "1"}})["result"]
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        self.proc.stdin.flush()
        return info

    def tool(self, name: str, args: dict | None = None) -> tuple[str, list, bool]:
        """Returns (text, image blocks, is_error)."""
        res = self.rpc("tools/call", {"name": name, "arguments": args or {}})
        if "error" in res:
            return res["error"].get("message", ""), [], True
        blocks = res["result"].get("content", [])
        text = "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        return text, [b for b in blocks if b.get("type") == "image"], bool(res["result"].get("isError"))

    def close(self) -> None:
        self.guard.cancel()
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=20)
        except Exception:
            self.proc.kill()
        self.err.close()


def png_size(path: str) -> tuple[int, int]:
    with open(path, "rb") as f:
        return struct.unpack(">II", f.read(24)[16:24])


def path_line(text: str, suffix: str) -> str | None:
    for line in text.splitlines():
        line = line.strip()
        if line.endswith(suffix) and os.path.isabs(line):
            return line
    return None


def demo_session() -> None:
    c = Client({"FLOW_DEMO": "1"}, "demo")
    info = c.start()
    print(f"INFO server {info['serverInfo']} started in {time.time() - c.started:.1f}s", flush=True)
    check("initialize", info["serverInfo"]["name"] == "google-flow-mcp")
    check("instructions mention demo mode", "DEMO MODE" in info.get("instructions", ""))
    check("21 tools", len(c.rpc("tools/list")["result"]["tools"]) == 21)
    check("3 prompts", len(c.rpc("prompts/list")["result"]["prompts"]) == 3)

    text, _, err = c.tool("flow_list_presets")
    check("ffmpeg available", "ffmpeg: found" in text and not err)

    text, imgs, err = c.tool("flow_generate_image", {"prompt": "a lighthouse at dawn", "preset": "pinterest-pin"})
    image = path_line(text, ".png")
    check("quick image saved with the 2:3 preset", bool(image) and os.path.isfile(image) and png_size(image) == (560, 840) and not err)
    check("preview returned to the assistant", len(imgs) == 1)

    text, _, err = c.tool("flow_project", {"name": "Smoke Test", "aspect_ratio": "9:16", "style": "warm watercolor"})
    check("project created", "smoke-test" in text and not err)
    text, imgs, err = c.tool("flow_ingredient_save", {"name": "mira", "description": "a girl in a yellow raincoat", "generate": True})
    check("ingredient with reference sheet", "Generated a reference sheet" in text and len(imgs) == 1 and not err)
    text, _, err = c.tool("flow_storyboard_plan", {"shots": [
        {"prompt": "@mira folds a paper rocket by a rainy window", "camera": "push-in", "duration": 3},
        {"prompt": "@mira carries the rocket to the rooftop at dusk", "camera": "tracking", "duration": 3},
        {"prompt": "The paper rocket flies toward a huge full moon", "camera": "crane-up", "duration": 4},
    ]})
    check("storyboard plan with estimates", "3 shot(s), 10s" in text and "~$0.23" in text and not err)
    text, imgs, err = c.tool("flow_storyboard_keyframes")
    check("keyframes + contact sheet", "3/3 generated" in text and len(imgs) == 1 and not err)

    began = time.time()
    text, _, err = c.tool("flow_storyboard_render", {"quality": "draft", "wait_seconds": 1})
    check("render call returns promptly", time.time() - began < 60 and not err,
          "handed to background" if "still rendering" in text else "finished within the wait")
    status = ""
    while time.time() - began < 300:
        status, _, _ = c.tool("flow_project")
        if status.count("[rendered]") == 3:
            break
        time.sleep(2)
    check("all shots rendered", status.count("[rendered]") == 3, f"{time.time() - began:.1f}s")

    text, _, err = c.tool("flow_edit_video", {"prompt": "Add light snowfall", "shot": 2})
    check("shot edit becomes a new take", "take 2 is now selected" in text and not err)
    text, _, err = c.tool("flow_shot_update", {"shot": 3, "trim_end": 2.0})
    check("shot trimmed", "trim end" in text and not err)
    text, _, err = c.tool("flow_generate_music", {"prompt": "warm lo-fi piano"})
    check("music attached", "Attached to project" in text and not err)
    text, _, err = c.tool("flow_generate_narration", {"text": "비 오는 저녁, 미라는 종이로 로켓을 접었습니다.", "voice": "Sulafat"})
    check("narration attached (non-Latin text)", "Attached to project" in text and not err)

    text, imgs, err = c.tool("flow_assemble")
    film = path_line(text, ".mp4")
    check("film assembled with music and narration",
          "Film assembled: 3 shot(s)" in text and "with music" in text and "with narration" in text and not err,
          text.splitlines()[0] if text else "")
    check("film file exists", bool(film) and os.path.isfile(film) and os.path.getsize(film) > 20000)
    text, imgs, err = c.tool("flow_review", {"path": film or "", "frames": 6})
    check("review returns frames; film stayed vertical with audio", "360x640" in text and "audio yes" in text and len(imgs) == 1 and not err, text[:90])

    text, _, err = c.tool("flow_board")
    board = os.path.join(OUT, "projects", "smoke-test", "board.html")
    html = open(board, encoding="utf-8").read() if os.path.isfile(board) else ""
    check("board.html has the film and three shots", html.count("<video") == 4 and "<audio" in html and not err)
    text, _, err = c.tool("flow_usage_today")
    check("nothing billed", "~$0.00" in text and not err)

    text, _, err = c.tool("flow_review", {"path": os.path.join(OUT, "missing.mp4")})
    check("a failing tool explains why", err and "File not found" in text, text[:120])
    text, _, err = c.tool("flow_shot_update", {"shot": 99, "duration": 5})
    check("a wrong shot number is explained", err and "Shot 99 not found" in text, text[:120])
    c.close()


def no_key_session() -> None:
    c = Client({}, "nokey")
    c.start()
    text, _, err = c.tool("flow_generate_image", {"prompt": "a red apple"})
    check("without a key the error says how to fix it", err and "GOOGLE_API_KEY" in text and "FLOW_DEMO=1" in text, text[:140])
    text, _, err = c.tool("flow_project")
    check("local tools work without a key", "smoke-test" in text and not err)
    c.close()


if __name__ == "__main__":
    demo_session()
    no_key_session()
    print(f"SUMMARY {sum(results)}/{len(results)} checks passed. Output: {OUT}", flush=True)
    sys.exit(0 if all(results) else 1)
