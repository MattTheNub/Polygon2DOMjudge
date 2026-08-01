#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


BINARY_SUFFIXES = {
    ".7z",
    ".bin",
    ".bmp",
    ".class",
    ".dll",
    ".exe",
    ".gif",
    ".gz",
    ".ico",
    ".jar",
    ".jpeg",
    ".jpg",
    ".o",
    ".pdf",
    ".png",
    ".so",
    ".tar",
    ".tgz",
    ".webp",
    ".zip",
}


def main() -> int:
    root = Path(sys.argv[1])
    changed = 0

    for path in root.rglob("*"):
        if path.is_file() and normalize_file(path):
            changed += 1

    if changed:
        print(f"Normalized CRLF to LF in {changed} files.")
    return 0


def normalize_file(path: Path) -> bool:
    if path.suffix.lower() in BINARY_SUFFIXES:
        return False

    data = path.read_bytes()
    if b"\r\n" not in data or b"\0" in data[:8192]:
        return False

    path.write_bytes(data.replace(b"\r\n", b"\n"))
    return True


if __name__ == "__main__":
    raise SystemExit(main())
