#!/usr/bin/env python3
"""Read-only environment inventory; no installs, model loads, or paid API calls."""
import importlib.metadata
import json
import platform
import shutil
import subprocess
from datetime import datetime, timezone


def run(command):
    if shutil.which(command[0]) is None:
        return {"status": "not_found"}
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=15)
        return {"status": "ok" if result.returncode == 0 else "failed",
                "returncode": result.returncode, "output": result.stdout.strip(),
                "error": result.stderr.strip()}
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"status": "failed", "error": type(error).__name__}


def collect():
    report = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "os": platform.system(), "release": platform.release(),
        "architecture": platform.machine(), "python": platform.python_version(),
        "tools": {name: shutil.which(name) for name in ["docker", "nvidia-smi", "nvcc", "vllm", "uv"]},
        "packages": {},
    }
    for name in ["vllm", "torch", "mlx", "vllm-metal"]:
        try:
            report["packages"][name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            report["packages"][name] = None
    report["nvidia_gpus"] = run([
        "nvidia-smi", "--query-gpu=name,memory.total,memory.free,driver_version",
        "--format=csv,noheader"])
    report["cuda_toolkit"] = run(["nvcc", "--version"])
    report["docker_client"] = run(["docker", "--version"])
    # Do not list container names, process owners, host names, or hardware serials.
    if platform.system() == "Darwin":
        report["macos"] = run(["sw_vers", "-productVersion"])
        report["cpu"] = run(["sysctl", "-n", "machdep.cpu.brand_string"])
        report["memory_bytes"] = run(["sysctl", "-n", "hw.memsize"])
        if any(report[key]["status"] != "ok" for key in ["cpu", "memory_bytes"]):
            hardware = run(["system_profiler", "SPHardwareDataType", "-json"])
            if hardware["status"] == "ok":
                try:
                    item = json.loads(hardware["output"])["SPHardwareDataType"][0]
                    report["apple_hardware"] = {
                        key: item.get(key) for key in
                        ["machine_name", "chip_type", "physical_memory", "number_processors"]
                    }
                except (ValueError, KeyError, IndexError, TypeError):
                    report["apple_hardware"] = {"status": "parse_failed"}
    elif platform.system() == "Linux":
        report["memory"] = run(["free", "-m"])
        report["disk_current_directory"] = run(["df", "-h", "."])
    return report


if __name__ == "__main__":
    print(json.dumps(collect(), ensure_ascii=False, indent=2))
