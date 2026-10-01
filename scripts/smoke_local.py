"""Launch the real server in explicit fake mode and exercise its public RPCs."""

import os
import socket
import subprocess
import sys
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    paths = [str(root / folder) for folder in ("generated", "examples", ".")]
    environment = os.environ.copy()
    environment.update(
        PYTHONPATH=os.pathsep.join(paths),
        PYTHONUTF8="1",
        MODEL_MODE="fake",
        OPENAI_API_KEY="",
    )
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        environment["PORT"] = str(reservation.getsockname()[1])
    environment["GRPC_HOST"] = "0.0.0.0"
    with subprocess.Popen(
        [sys.executable, "-m", "v2.server"], cwd=root, env=environment
    ) as process:
        try:
            result = subprocess.run(
                [sys.executable, "-m", "v2.smoke"],
                cwd=root,
                env=environment,
                check=False,
            )
            if result.returncode:
                raise SystemExit(result.returncode)
        finally:
            process.terminate()
            process.wait(timeout=10)


if __name__ == "__main__":
    main()
