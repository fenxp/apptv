#!/usr/bin/env python3
"""Build the minimal static directory published by Cloudflare Pages."""

from __future__ import annotations

import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "dist"
PUBLIC_ITEMS = ("index.html", ".nojekyll", "assets", "data")


def build_site(root: Path = ROOT, output: Path = OUTPUT) -> Path:
    root = root.resolve()
    output = output.resolve()
    if output == root or root not in output.parents:
        raise ValueError("Output directory must be inside the project root")

    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    for name in PUBLIC_ITEMS:
        source = root / name
        if not source.exists():
            raise FileNotFoundError(f"Missing public site item: {source}")
        destination = output / name
        if source.is_dir():
            shutil.copytree(source, destination)
        else:
            shutil.copy2(source, destination)

    return output


if __name__ == "__main__":
    print(f"Cloudflare Pages output: {build_site()}")

