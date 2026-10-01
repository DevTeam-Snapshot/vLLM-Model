"""Launch the model server with portable generated-module search paths."""

import os
from pathlib import Path
from subprocess import run
from sys import executable


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONPATH"] = os.pathsep.join(
        str(root / folder) for folder in ("generated", "examples", ".")
    )
    run([executable, "-m", "v2.server"], cwd=root, env=environment, check=True)


if __name__ == "__main__":
    main()
