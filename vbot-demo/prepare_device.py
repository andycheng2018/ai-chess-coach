#!/usr/bin/env python3
"""Stage the existing release's verified ARM64 wheels locally; never contact a robot."""
import argparse
import hashlib
from pathlib import Path
import shutil

WHEELS = (
    "aorta_sdk-2026.9.23-py3-none-linux_aarch64.whl",
    "aorta_msgs-2026.9.23-py3-none-any.whl",
    "vbot_edu_msgs-2026.9.24-py3-none-any.whl",
    "flatbuffers-25.12.19-py2.py3-none-any.whl",
)


def stage(source, destination):
    source, destination = Path(source), Path(destination)
    expected = {}
    for line in (source / "SHA256SUMS").read_text().splitlines():
        parts = line.split()
        if len(parts) == 2:
            expected[parts[1].lstrip("*")] = parts[0]
    # Verify all inputs before writing any output.
    for name in WHEELS:
        digest = hashlib.sha256((source / name).read_bytes()).hexdigest()
        if expected.get(name) != digest:
            raise ValueError(f"Checksum missing or mismatched: {name}")
    names = (*WHEELS, "SHA256SUMS", "EDU_SDK_MANIFEST.json")
    if (source / "flatbuffers-25.12.19.LICENSE").exists():
        names += ("flatbuffers-25.12.19.LICENSE",)
    for name in names:
        if not (source / name).is_file():
            raise ValueError(f"Missing release artifact: {name}")
        target = destination / name
        if target.exists() and target.read_bytes() != (source / name).read_bytes():
            raise ValueError(f"Refusing to replace a different artifact: {target.name}")
    destination.mkdir(parents=True, exist_ok=True)
    for name in names:
        target = destination / name
        shutil.copy2(source / name, target)
    print(f"Verified and staged four Linux ARM64 deployment wheels in {destination}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk-dir", required=True, type=Path)
    args = parser.parse_args()
    stage(args.sdk_dir, Path(__file__).resolve().parent / "wheelhouse")
