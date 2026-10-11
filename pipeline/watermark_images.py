#!/usr/bin/env python3
"""Create faintly branded review copies of image assets without modifying originals.

Accepts a dataset directory containing images/ or a pipeline batch directory
containing assets/. Outputs go in a separate watermarked/ folder; source images
and dataset JSON are never modified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

SUPPORTED = {".jpg", ".jpeg", ".png", ".webp"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def choose_font(size: int) -> ImageFont.ImageFont:
    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ):
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def watermark_image(source: Path, destination: Path, text: str) -> dict[str, Any]:
    with Image.open(source) as opened:
        original = opened.convert("RGB")
    width, height = original.size
    font_size = max(12, min(30, width // 22))
    font = choose_font(font_size)

    # Very low-opacity diagonal pattern; original files remain unchanged.
    tile_w = max(220, int(font_size * max(len(text), 10) * 0.72))
    tile_h = max(120, int(font_size * 5.5))
    tile = Image.new("RGBA", (tile_w, tile_h), (255, 255, 255, 0))
    ImageDraw.Draw(tile).text(
        (font_size // 2, tile_h // 3),
        text,
        font=font,
        fill=(35, 82, 145, 22),
        stroke_width=0,
    )
    tile = tile.rotate(28, resample=Image.Resampling.BICUBIC, expand=True)

    overlay = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    for y in range(0, height, tile.height):
        for x in range(0, width, tile.width):
            overlay.alpha_composite(tile, (x, y))

    branded = Image.alpha_composite(original.convert("RGBA"), overlay).convert("RGB")
    destination.parent.mkdir(parents=True, exist_ok=True)
    suffix = destination.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        branded.save(destination, format="JPEG", quality=95, optimize=True)
        mime = "image/jpeg"
    elif suffix == ".png":
        branded.save(destination, format="PNG", optimize=True)
        mime = "image/png"
    else:
        branded.save(destination, format="WEBP", quality=95, method=6)
        mime = "image/webp"

    return {
        "source_path": source.as_posix(),
        "source_sha256": sha256(source),
        "output_path": destination.as_posix(),
        "output_sha256": sha256(destination),
        "width": width,
        "height": height,
        "mime_type": mime,
        "bytes": destination.stat().st_size,
    }


def build(data_dir: Path, text: str) -> dict[str, Any]:
    text = text.strip()
    if not text:
        raise SystemExit("Watermark text must not be empty")
    if (data_dir / "images").is_dir():
        image_root = data_dir / "images"
    elif (data_dir / "assets").is_dir():
        image_root = data_dir / "assets"
    else:
        raise SystemExit(f"No images/ or assets/ directory found in {data_dir}")

    output_root = image_root / "watermarked"
    sources = sorted(
        p for p in image_root.rglob("*")
        if p.is_file()
        and p.suffix.lower() in SUPPORTED
        and output_root not in p.parents
    )
    if not sources:
        raise SystemExit(f"No source images found under {image_root}")

    entries = []
    for source in sources:
        relative = source.relative_to(image_root)
        destination = output_root / relative
        entries.append(watermark_image(source, destination, text))

    manifest = {
        "schema_version": "1.0.0",
        "status": "BRANDED_REVIEW_ONLY",
        "watermark_text": text,
        "method": "repeated low-opacity diagonal overlay",
        "source_root": image_root.as_posix(),
        "output_root": output_root.as_posix(),
        "source_image_count": len(entries),
        "outputs": entries,
        "source_images_modified": False,
        "dataset_json_modified": False,
        "production_import": "NOT_PERFORMED",
        "review_note": (
            "These are branded derivatives for visual review. Confirm text and "
            "diagram readability and ensure rights/permissions for each source "
            "asset before public publication. Original images are preserved."
        ),
    }
    (data_dir / "watermark-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, help="Dataset or pipeline batch directory")
    parser.add_argument("--text", default="JEE PYQ Master", help="Watermark text")
    args = parser.parse_args()
    result = build(Path(args.data_dir), args.text)
    print(json.dumps({
        "status": result["status"],
        "source_image_count": result["source_image_count"],
        "watermark_text": result["watermark_text"],
        "source_images_modified": result["source_images_modified"],
        "dataset_json_modified": result["dataset_json_modified"],
        "manifest": str(Path(args.data_dir) / "watermark-manifest.json"),
        "production_import": result["production_import"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
