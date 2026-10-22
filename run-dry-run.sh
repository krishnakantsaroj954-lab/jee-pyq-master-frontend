#!/usr/bin/env bash
set -Eeuo pipefail

# Source-specific dry run. It uses the pinned Jan 22 page images in the quarantined
# bundle, not the different Jan 28 PDF at repository root. Never imports to D1.

CONFIG="representative-config.json"

echo "=== JEE PYQ source-grounded OCR dry run ==="
echo "Target: JEE Main · 22 January 2026 · Shift 1"
echo

if ! command -v tesseract >/dev/null 2>&1; then
  echo "BLOCKED: Tesseract OCR is required for this scanned paper." >&2
  echo "Install it first (Termux: pkg install tesseract; Ubuntu: sudo apt-get install tesseract-ocr)." >&2
  exit 2
fi

echo "[1/4] Installing Python package dependencies..."
python -m pip install -e .

echo
echo "[2/4] Verifying pinned Jan 22 source-page checksums and preparing OCR derivative..."
python scripts/prepare_jan22_source_pdf.py
python scripts/verify_jan22_source.py

echo
echo "[3/4] Running OCR extraction (no production import)..."
# Each run gets a fresh folder. Existing review evidence/output is never deleted.
RUN_STAMP="$(date -u +%Y%m%dT%H%M%SZ)-$$"
OUT_ROOT="pipeline-output/jan22-run-$RUN_STAMP"
mkdir -p "$OUT_ROOT"

set +e
PYTHONPATH=pipeline python -m jee_pyq_pipeline.cli \
  --config "$CONFIG" \
  --output "$OUT_ROOT" \
  --max-pages 24 \
  --timeout-seconds 2400
PIPELINE_RC=$?
set -e

BATCH_DIR="$(find "$OUT_ROOT" -mindepth 2 -maxdepth 2 -type f -name batch-manifest.json -print -quit | sed 's#/batch-manifest.json$##')"
if [[ -z "$BATCH_DIR" || ! -f "$BATCH_DIR/validation-report.json" ]]; then
  echo "FAILED: extraction did not create a complete batch manifest/report (CLI exit=$PIPELINE_RC)." >&2
  exit 2
fi

echo
echo "[4/4] Dry-run report..."
python - "$BATCH_DIR" "$PIPELINE_RC" <<'PY'
import json, sys
from pathlib import Path

batch = Path(sys.argv[1])
cli_rc = int(sys.argv[2])
manifest = json.loads((batch / "batch-manifest.json").read_text(encoding="utf-8"))
report = json.loads((batch / "validation-report.json").read_text(encoding="utf-8"))
prepared_path = Path("pipeline-output/source/22jan-source-page-verification.json")
prepared = json.loads(prepared_path.read_text(encoding="utf-8")) if prepared_path.is_file() else {}

print(f"Batch: {batch}")
print(f"Status: {manifest.get('status', 'UNKNOWN')}")
print(f"CLI exit code: {cli_rc} (exit 2 is expected when review/quarantine gates block readiness)")
print(f"Original PDF recorded in verified source manifest: {prepared.get('original_source_pdf', 'unknown')}")
print(f"Original PDF SHA-256 recorded in manifest: {prepared.get('original_source_pdf_sha256_from_manifest', 'unknown')}")
print(f"Verified source page images: {prepared.get('page_assets_verified', 0)}/24")
print(f"Derivative OCR PDF SHA-256: {prepared.get('ocr_derivative_pdf_sha256', 'unknown')}")
for name in ("validated", "review_required", "quarantined", "rejected", "dropped"):
    path = batch / f"{name}.json"
    count = len(json.loads(path.read_text(encoding="utf-8"))) if path.is_file() else 0
    print(f"{name}: {count}")
print(f"Assets generated: {manifest.get('asset_count', 0)}")
issues = report.get("issues", [])
if isinstance(issues, list):
    print(f"Blocking/validation issues: {len(issues)}")
    counts = {}
    for item in issues:
        if isinstance(item, dict):
            code = str(item.get("code", "UNKNOWN"))
            counts[code] = counts.get(code, 0) + 1
    for code, count in sorted(counts.items()):
        print(f"  {code}: {count}")
print(f"Per-question source review gate: {report.get('review_gate', {}).get('status', 'UNKNOWN')}")
PY

echo
echo "DRY RUN COMPLETE. No D1 import, Cloudflare write, or production publish was performed."
echo "The reconstructed scan PDF is derived from checksum-verified page JPEGs, not byte-identical to the original PDF."
echo "Do not publish the extracted records until each question, option, answer, solution, and image is human-verified against the source."
