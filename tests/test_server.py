"""Unit tests for google_flow_mcp.server — all API calls are mocked."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# Set env vars before importing the server module
os.environ.setdefault("GOOGLE_API_KEY", "test-api-key-000")
os.environ["FLOW_OUTPUT_DIR"] = tempfile.mkdtemp()

import google_flow_mcp.server as server_module  # noqa: E402
from google_flow_mcp.server import (  # noqa: E402
    MODEL_IMAGE_FLASH,
    MODEL_IMAGE_PRO,
    MODEL_VIDEO,
    flow_edit_image,
    flow_extend_video,
    flow_generate_image,
    flow_generate_image_with_references,
    flow_generate_video,
    flow_image_to_video,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset the lazy client singleton between tests."""
    server_module._client = None
    yield
    server_module._client = None


@pytest.fixture
def mock_client(mocker) -> MagicMock:
    """Patch _get_client to return a fully mocked async client."""
    client = MagicMock()
    client.aio = MagicMock()
    client.aio.models = MagicMock()
    client.aio.models.generate_images = AsyncMock()
    client.aio.models.edit_image = AsyncMock()
    client.aio.models.generate_videos = AsyncMock()
    client.aio.operations = MagicMock()
    client.aio.operations.get = AsyncMock()
    mocker.patch.object(server_module, "_get_client", return_value=client)
    return client


def _fake_gen_image(tmp_path: Path, name: str = "out.png") -> MagicMock:
    """Build a mock GeneratedImage whose .image.save() actually creates a file."""
    path_ref: list[Path] = []
    target = tmp_path / name

    gen = MagicMock()
    gen.image.image_bytes = None

    def save_side(path_str: str) -> None:
        p = Path(path_str)
        path_ref.append(p)
        p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)

    gen.image.save.side_effect = save_side
    gen.image._save_target = target
    return gen


def _fake_video_operation(uri: str = "gs://bucket/out.mp4", done: bool = True) -> MagicMock:
    """Build a mock Veo operation that is immediately done."""
    op = MagicMock()
    op.done = done
    op.error = MagicMock()
    op.error.message = None
    vid = MagicMock()
    vid.video.video_bytes = None
    vid.video.uri = uri
    op.response.generated_videos = [vid]
    return op


def _write_tmp_png(tmp_path: Path, name: str = "input.png") -> str:
    """Write a minimal PNG file and return its path as string."""
    p = tmp_path / name
    p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    return str(p)


def _write_tmp_mp4(tmp_path: Path, name: str = "input.mp4") -> str:
    p = tmp_path / name
    p.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 32)
    return str(p)


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_01_generate_image_default_model(mock_client, tmp_path):
    """flow_generate_image uses MODEL_IMAGE_PRO by default."""
    gen = _fake_gen_image(tmp_path)
    mock_client.aio.models.generate_images.return_value.generated_images = [gen]

    result = await flow_generate_image(prompt="a red apple", output_dir=str(tmp_path))

    call_kwargs = mock_client.aio.models.generate_images.call_args.kwargs
    assert call_kwargs["model"] == MODEL_IMAGE_PRO
    assert call_kwargs["prompt"] == "a red apple"
    assert "flow_image_" in result


@pytest.mark.asyncio
async def test_02_generate_image_flash_model(mock_client, tmp_path):
    """Passing model='flash' selects MODEL_IMAGE_FLASH."""
    gen = _fake_gen_image(tmp_path)
    mock_client.aio.models.generate_images.return_value.generated_images = [gen]

    await flow_generate_image(prompt="quick sketch", model="flash", output_dir=str(tmp_path))

    call_kwargs = mock_client.aio.models.generate_images.call_args.kwargs
    assert call_kwargs["model"] == MODEL_IMAGE_FLASH


@pytest.mark.asyncio
async def test_03_generate_image_count_clamped_to_4(mock_client, tmp_path):
    """number_of_images is clamped to max 4 before being sent to the API."""
    gens = [_fake_gen_image(tmp_path, f"img{i}.png") for i in range(4)]
    mock_client.aio.models.generate_images.return_value.generated_images = gens

    result = await flow_generate_image(
        prompt="many apples", number_of_images=99, output_dir=str(tmp_path)
    )

    config_arg = mock_client.aio.models.generate_images.call_args.kwargs["config"]
    assert config_arg.number_of_images == 4
    assert "4 image(s)" in result


@pytest.mark.asyncio
async def test_04_generate_image_multiple_files_saved(mock_client, tmp_path):
    """Result lists all saved paths when multiple images are returned."""
    gens = [_fake_gen_image(tmp_path, f"r{i}.png") for i in range(3)]
    mock_client.aio.models.generate_images.return_value.generated_images = gens

    result = await flow_generate_image(
        prompt="trio", number_of_images=3, output_dir=str(tmp_path)
    )

    assert "3 image(s)" in result
    assert result.count("flow_image_") == 3


@pytest.mark.asyncio
async def test_05_edit_image_passes_reference(mock_client, tmp_path):
    """flow_edit_image passes a RawReferenceImage to generate_images."""
    src = _write_tmp_png(tmp_path, "src.png")
    gen = _fake_gen_image(tmp_path, "edited.png")
    mock_client.aio.models.edit_image.return_value.generated_images = [gen]

    result = await flow_edit_image(
        image_path=src, prompt="make it blue", output_dir=str(tmp_path)
    )

    call_kwargs = mock_client.aio.models.edit_image.call_args.kwargs
    ref_images = call_kwargs["reference_images"]
    assert len(ref_images) == 2  # RawReferenceImage + MaskReferenceImage
    assert "flow_edit_" in result


@pytest.mark.asyncio
async def test_06_generate_with_references_passes_all_refs(mock_client, tmp_path):
    """flow_generate_image_with_references passes one RawReferenceImage per path."""
    paths = [_write_tmp_png(tmp_path, f"ref{i}.png") for i in range(3)]
    gen = _fake_gen_image(tmp_path, "out.png")
    mock_client.aio.models.generate_images.return_value.generated_images = [gen]

    result = await flow_generate_image_with_references(
        prompt="inspired by these", reference_image_paths=paths, output_dir=str(tmp_path)
    )

    call_kwargs = mock_client.aio.models.generate_images.call_args.kwargs
    assert len(call_kwargs["reference_images"]) == 3
    assert "3 reference(s)" in result


@pytest.mark.asyncio
async def test_07_generate_with_references_too_many_raises(mock_client, tmp_path):
    """More than 14 reference images raises ValueError."""
    paths = [_write_tmp_png(tmp_path, f"r{i}.png") for i in range(15)]

    with pytest.raises(ValueError, match="14"):
        await flow_generate_image_with_references(
            prompt="too many", reference_image_paths=paths, output_dir=str(tmp_path)
        )


@pytest.mark.asyncio
async def test_08_generate_video_success(mock_client, tmp_path):
    """flow_generate_video calls generate_videos with MODEL_VIDEO and returns URI."""
    op = _fake_video_operation(uri="gs://bucket/vid.mp4")
    mock_client.aio.models.generate_videos.return_value = op

    result = await flow_generate_video(prompt="drone over mountains", output_dir=str(tmp_path))

    call_kwargs = mock_client.aio.models.generate_videos.call_args.kwargs
    assert call_kwargs["model"] == MODEL_VIDEO
    assert "SynthID" in result


@pytest.mark.asyncio
async def test_09_generate_video_polls_until_done(mock_client, tmp_path):
    """flow_generate_video polls the operation when initially not done."""
    op_pending = _fake_video_operation(done=False)
    op_done = _fake_video_operation(done=True, uri="gs://bucket/final.mp4")
    mock_client.aio.models.generate_videos.return_value = op_pending
    mock_client.aio.operations.get.return_value = op_done

    # Patch sleep to avoid actual delay
    import asyncio
    from unittest.mock import patch

    with patch.object(asyncio, "sleep", new_callable=AsyncMock):
        result = await flow_generate_video(prompt="slow sunrise", output_dir=str(tmp_path))

    mock_client.aio.operations.get.assert_called_once_with(op_pending)
    assert "SynthID" in result


@pytest.mark.asyncio
async def test_10_image_to_video_generates_anchor_then_video(mock_client, tmp_path):
    """flow_image_to_video calls generate_images first, then generate_videos."""
    gen = _fake_gen_image(tmp_path, "anchor.png")
    mock_client.aio.models.generate_images.return_value.generated_images = [gen]

    op = _fake_video_operation(uri="gs://bucket/final.mp4")
    mock_client.aio.models.generate_videos.return_value = op

    result = await flow_image_to_video(
        video_prompt="the scene comes alive",
        image_prompt="a tranquil mountain lake at dawn",
        output_dir=str(tmp_path),
    )

    mock_client.aio.models.generate_images.assert_called_once()
    mock_client.aio.models.generate_videos.assert_called_once()
    assert "Anchor image" in result
    assert "SynthID" in result
