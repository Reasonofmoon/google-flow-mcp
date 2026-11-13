"""The MCP layer itself: content blocks from a tool call, and a real stdio server process."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading

import google_flow_mcp.server as server

from .conftest import write_png


async def test_tool_call_returns_text_and_image_blocks(tmp_path):
    result = await server.mcp.call_tool("flow_review", {"path": write_png(tmp_path)})
    blocks = getattr(result, "content", result)  # mcp 2.x: CallToolResult; 1.x: list or (list, dict)
    if isinstance(blocks, tuple):
        blocks = blocks[0]
    assert [b.type for b in blocks] == ["text", "image"]
    assert "320x180" in blocks[0].text and len(blocks[1].data) > 100


def test_stdio_server_speaks_mcp(tmp_path):
    """Start `python -m google_flow_mcp` and talk JSON-RPC to it like a desktop client does."""
    env = {k: v for k, v in os.environ.items() if k not in ("GOOGLE_API_KEY", "GEMINI_API_KEY", "FLOW_DEMO")}
    env.update({"FLOW_OUTPUT_DIR": str(tmp_path), "PYTHONUNBUFFERED": "1"})
    proc = subprocess.Popen([sys.executable, "-m", "google_flow_mcp"], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", env=env)
    guard = threading.Timer(60, proc.kill)
    guard.start()

    def send(msg: dict) -> None:
        proc.stdin.write(json.dumps(msg) + "\n")
        proc.stdin.flush()

    def reply(msg_id: int) -> dict:
        while True:
            line = proc.stdout.readline()
            assert line, "server closed stdout: " + proc.stderr.read()[-800:]
            if line.lstrip().startswith("{"):
                data = json.loads(line)
                if data.get("id") == msg_id:
                    assert "error" not in data, data
                    return data["result"]

    try:
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "pytest", "version": "0"}}})
        info = reply(1)
        assert info["serverInfo"]["name"] == "google-flow-mcp" and "FILMS" in info["instructions"]
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})

        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tools = {t["name"]: t for t in reply(2)["tools"]}
        assert len(tools) == 21
        assert tools["flow_storyboard_plan"]["inputSchema"]["properties"]["shots"]["type"] == "array"

        send({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
              "params": {"name": "flow_list_presets", "arguments": {}}})
        text = reply(3)["content"][0]["text"]
        assert "push-in" in text and "pinterest-pin" in text

        send({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
              "params": {"name": "flow_project", "arguments": {"name": "Smoke Test", "aspect_ratio": "9:16"}}})
        assert "smoke-test" in reply(4)["content"][0]["text"]
        assert (tmp_path / "projects" / "smoke-test" / "board.html").exists()

        send({"jsonrpc": "2.0", "id": 5, "method": "prompts/list"})
        assert {p["name"] for p in reply(5)["prompts"]} == {"short_film", "product_ad", "social_image_set"}

        # A failing tool must tell the client why (mcp 2.x hides non-ToolError messages).
        send({"jsonrpc": "2.0", "id": 6, "method": "tools/call",
              "params": {"name": "flow_generate_image", "arguments": {"prompt": "a red apple"}}})
        failed = reply(6)
        assert failed["isError"] is True
        message = failed["content"][0]["text"]
        assert "GOOGLE_API_KEY" in message and "FLOW_DEMO=1" in message, message

        send({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
              "params": {"name": "flow_shot_update", "arguments": {"shot": 9, "duration": 5}}})
        failed = reply(7)
        assert failed["isError"] is True and "Shot 9 not found" in failed["content"][0]["text"]
    finally:
        guard.cancel()
        proc.stdin.close()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
