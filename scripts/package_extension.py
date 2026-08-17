#!/usr/bin/env python3
"""Build a deterministic content-free Chrome Web Store ZIP."""

from __future__ import annotations

import argparse
import json
import stat
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "extension"
ALLOWED_SUFFIXES = {".css", ".html", ".js", ".json", ".mjs", ".png", ".svg"}


def package_extension(output: Path | None = None) -> dict[str, object]:
    manifest = json.loads((EXTENSION / "manifest.json").read_text(encoding="utf-8"))
    version = manifest.get("version")
    if not isinstance(version, str) or not version:
        raise ValueError("extension manifest has no version")
    files = sorted(path for path in EXTENSION.iterdir() if path.is_file())
    if not files or any(
        path.suffix not in ALLOWED_SUFFIXES or path.name.startswith(".")
        for path in files
    ):
        raise ValueError("extension directory contains an unsupported package asset")
    destination = output or ROOT / "dist" / f"llm-wiki-for-chrome-{version}.zip"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for path in files:
            info = zipfile.ZipInfo(path.name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, path.read_bytes())
    return {
        "artifact": str(destination.resolve(strict=False)),
        "file_count": len(files),
        "version": version,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print(json.dumps(package_extension(args.output), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
