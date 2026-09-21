"""Generate both contracts using the interpreter's installed grpcio-tools."""

from pathlib import Path
from subprocess import run
from sys import executable


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    (root / "generated").mkdir(exist_ok=True)
    run(
        [
            executable,
            "-m",
            "grpc_tools.protoc",
            "-I",
            "proto",
            "--python_out=generated",
            "--pyi_out=generated",
            "--grpc_python_out=generated",
            "proto/hotel_ad_image.proto",
            "proto/hotel_ad_v2.proto",
        ],
        cwd=root,
        check=True,
    )


if __name__ == "__main__":
    main()
