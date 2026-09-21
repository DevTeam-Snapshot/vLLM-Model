"""Run regression tests portably without changing imported contract artifacts."""

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
    run(
        [executable, "scripts/generate_stubs.py"], cwd=root, env=environment, check=True
    )
    run(
        [executable, "-m", "pytest", "tests", "-q", "-p", "no:cacheprovider"],
        cwd=root,
        env=environment,
        check=True,
    )


if __name__ == "__main__":
    main()
