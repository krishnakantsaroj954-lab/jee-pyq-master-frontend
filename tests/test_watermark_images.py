import json
from pathlib import Path

from PIL import Image

from pipeline.watermark_images import build


def make_image(path: Path, size=(360, 180)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, "white").save(path, quality=95)


def test_watermark_creates_separate_review_copy_and_preserves_source(tmp_path: Path):
    root = tmp_path / "paper"
    source = root / "images" / "questions" / "q001_figure.jpg"
    make_image(source)
    original_bytes = source.read_bytes()

    result = build(root, "JEE PYQ Master")

    output = root / "images" / "watermarked" / "questions" / "q001_figure.jpg"
    assert output.is_file()
    assert source.read_bytes() == original_bytes
    assert result["source_image_count"] == 1
    assert result["source_images_modified"] is False
    assert result["dataset_json_modified"] is False
    with Image.open(output) as image:
        assert image.size == (360, 180)
    manifest = json.loads((root / "watermark-manifest.json").read_text())
    assert manifest["outputs"][0]["source_sha256"]
    assert manifest["outputs"][0]["output_sha256"]
    assert manifest["production_import"] == "NOT_PERFORMED"


def test_watermark_accepts_pipeline_batch_assets(tmp_path: Path):
    root = tmp_path / "batch"
    source = root / "assets" / "run123" / "page-1" / "img-0.png"
    source.parent.mkdir(parents=True)
    Image.new("RGB", (240, 120), "white").save(source)
    original_bytes = source.read_bytes()

    result = build(root, "JEE PYQ Master")

    output = root / "assets" / "watermarked" / "run123" / "page-1" / "img-0.png"
    assert output.is_file()
    assert source.read_bytes() == original_bytes
    assert result["source_image_count"] == 1
    assert result["source_root"].endswith("assets")
    assert result["source_images_modified"] is False


def test_watermark_skips_its_own_output_folder(tmp_path: Path):
    root = tmp_path / "paper"
    source = root / "images" / "pages" / "page_01.jpg"
    make_image(source, (240, 120))
    build(root, "JEE PYQ Master")
    second = build(root, "JEE PYQ Master")
    assert second["source_image_count"] == 1
