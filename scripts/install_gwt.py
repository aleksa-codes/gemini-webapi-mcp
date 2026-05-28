#!/usr/bin/env python3
"""Download Allen Kuo's gwt-mini (GeminiWatermarkTool CLI) for the current OS.

Cross-platform: macOS (universal), Windows x64, Linux x64. Verifies SHA256,
extracts into ./tools/gwt/, strips quarantine on macOS, chmod +x on POSIX.

Usage:
    python scripts/install_gwt.py
    python scripts/install_gwt.py --version v0.3.1

Upstream: https://github.com/allenk/GeminiWatermarkTool (MIT, Allen Kuo)
"""
from __future__ import annotations

import argparse
import hashlib
import platform
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

GWT_VERSION = "v0.3.1"
GWT_REPO = "allenk/GeminiWatermarkTool"

# SHA256 from official SHA256SUMS.txt of the release
_ASSETS = {
    "Darwin": ("gwt-mini-macos-universal.zip",
               "a55f458250adfa74559366eaa4b9e52ec6e6eb4df72a5f9d8dc392994721e911",
               "gwt-mini"),
    "Linux":  ("gwt-mini-linux-x64.zip",
               "98028d53b84379e5671fcdecad1bd413ff1c303b1ca964e9744c608e897f552b",
               "gwt-mini"),
    "Windows": ("gwt-mini-windows-x64.zip",
                "677621412245885f52a6bd299faa9bc7f9db5dee6780a4ef05a97d86a3cd2a86",
                "gwt-mini.exe"),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", default=GWT_VERSION, help=f"Release tag (default {GWT_VERSION})")
    parser.add_argument("--force", action="store_true", help="Re-download even if binary exists")
    args = parser.parse_args()

    system = platform.system()
    if system not in _ASSETS:
        print(f"Unsupported platform: {system}", file=sys.stderr)
        return 1
    zip_name, sha256, exe_name = _ASSETS[system]

    repo_root = Path(__file__).resolve().parent.parent
    out_dir = repo_root / "tools" / "gwt"
    out_dir.mkdir(parents=True, exist_ok=True)
    binary = out_dir / exe_name

    if binary.exists() and not args.force:
        print(f"gwt-mini already installed: {binary}")
        print("Use --force to re-download.")
        return 0

    url = f"https://github.com/{GWT_REPO}/releases/download/{args.version}/{zip_name}"
    zip_path = out_dir / zip_name

    print(f"Downloading {url}")
    with urllib.request.urlopen(url) as resp, open(zip_path, "wb") as fh:
        shutil.copyfileobj(resp, fh)

    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    if digest != sha256:
        zip_path.unlink(missing_ok=True)
        print(f"SHA256 mismatch:\n  expected {sha256}\n  got      {digest}", file=sys.stderr)
        return 2
    print(f"SHA256 OK ({sha256[:16]}…)")

    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(out_dir)
    zip_path.unlink(missing_ok=True)

    if not binary.exists():
        print(f"Extracted archive but {exe_name} not found in {out_dir}", file=sys.stderr)
        return 3

    if system != "Windows":
        binary.chmod(0o755)
    if system == "Darwin":
        # Gatekeeper quarantine bit blocks unsigned binaries; allenk's release is unsigned.
        # Removing the flag is the same step the user would do via Finder ‘Open Anyway’.
        subprocess.run(["xattr", "-d", "com.apple.quarantine", str(binary)],
                       capture_output=True, check=False)

    print(f"Installed: {binary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
