import os
import socket
import subprocess
import sys
from pathlib import Path

import grpc
from PIL import Image, ImageDraw
from test_v2_draft_provider import provider as vision_provider
from test_v2_planning_vllm import provider as qwen_provider
from test_v2_vision import vision_reply


def test_live_cli_through_server_process(tmp_path: Path) -> None:
    # Given: live server configuration with local HTTP providers and a real image file.
    source = Image.new("RGB", (1200, 800), "#9aa9b8")
    draw = ImageDraw.Draw(source)
    draw.rectangle((700, 160, 1100, 560), fill="#d8ad73")
    draw.rectangle((100, 350, 600, 700), fill="#70889a")
    photo = tmp_path / "source.png"
    source.save(photo)
    environment = os.environ.copy()
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    with (
        qwen_provider('{"updates":{"lodging_type":1}}') as qwen,
        vision_provider(vision_reply()) as (url, received),
    ):
        environment.update(
            MODEL_MODE="live",
            GRPC_HOST="127.0.0.1",
            PORT=str(port),
            VLLM_BASE_URL=qwen.url,
            VLLM_MODEL="test",
            OPENAI_API_KEY="local-test-only",
            OPENAI_BASE_URL=url,
            PYTHONUTF8="1",
            LIVE_CHECK_TARGET=f"127.0.0.1:{port}",
        )
        with subprocess.Popen(
            [sys.executable, "-m", "v2.server"], env=environment
        ) as server:
            try:
                with grpc.insecure_channel(f"127.0.0.1:{port}") as channel:
                    grpc.channel_ready_future(channel).result(timeout=15)
                # When: the public live-check command runs against the real server process.
                result = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "v2.live_check",
                        str(photo),
                        str(tmp_path / "results"),
                    ],
                    env=environment,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=45,
                    check=False,
                )
                # Then: Qwen is called and all three drafts use the Vision endpoint.
                assert result.returncode == 0, result.stdout + result.stderr
                assert len(received) == 3
                assert any(path == "/v1/chat/completions" for path, _ in qwen.requests)
                paths = sorted((tmp_path / "results").glob("*/candidate-*.png"))
                assert len(paths) == 3
                for index, path in enumerate(paths, start=1):
                    with Image.open(path) as image:
                        assert image.info["layout_provider"] == "openai"
                        assert image.size == (
                            (1024, 683) if index == 1 else (1024, 1024)
                        )
                print(result.stdout)
            finally:
                server.terminate()
                server.wait(timeout=10)
