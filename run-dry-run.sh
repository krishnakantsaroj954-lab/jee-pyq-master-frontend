#!/usr/bin/env bash
set -Eeuo pipefail

# Source-specific, fail-closed dry run for the 22 January 2026 Shift 1 PDF.
# It never imports data into Cloudflare/D1 and never deletes earlier review evidence.

PDF="cEDaK5Wn5ILe4nOdotd6.pdf"
CONFIG="representative-config.json"

echo "=== JEE PYQ source-grounded OCR dry run ==="
echo "Target: JEE Main · 22 January 2026 · Shift 1"
echo

if [[ ! -f "$PDF" ]]; then
  echo "BLOCKED: expected source PDF was not found: $PDF" >&2
  exit 2
fi
if ! command -v tesseract >/dev/null 2>&1; then
  echo "BLOCKED: Tesseract OCR is required for this scanned PDF." >&2
  echo "Install it first (Termux: pkg install tesseract; Ubuntu: sudo apt-get install tesseract-ocr)." >&2
  exit 2
fi

echo "[1/4] Installing Python package dependencies..."
python -m pip install -e .

echo
echo "[2/4] Verifying exact source identity and question-number mapping..."
python scripts/verify_jan22_source.py

echo
echo "[3/4] Running OCR extraction (no production import)..."
# Use a unique output root; preserve all earlier manifests and review evidence.
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

print(f"Batch: {batch}")
print(f"Status: {manifest.get('status', 'UNKNOWN')}")
print(f"CLI exit code: {cli_rc} (exit 2 is expected when review/quarantine gates block readiness)")
for name in ("validated", "review_required", "quarantined", "rejected", "dropped"):
    path = batch / f"{name}.json"
    count = len(json.loads(path.read_text(encoding="utf-8"))) if path.is_file() else 0
    print(f"{name}: {count}")
print(f"Assets generated: {manifest.get('asset_count', 0)}")
if isinstance(report, dict):
    issues = report.get("issues", [])
    print(f"Validation report fields: {', '.join(sorted(report.keys()))}")
    if isinstance(issues, list):
        print(f"Blocking issues recorded: {len(issues)}")
        counts = {}
        for item in issues:
            if isinstance(item, dict):
                code = str(item.get("code", "UNKNOWN"))
                counts[code] = counts.get(code, 0) + 1
        for code, count in sorted(counts.items()):
            print(f"  {code}: {count}")
    elif isinstance(report.get("summary"), dict):
        print("Summary:", json.dumps(report["summary"], ensure_ascii=False, sort_keys=True))
PY

echo
echo "DRY RUN COMPLETE. No D1 import or production write was performed."
echo "Do not publish the extracted records unless a human verifies the source and completes the content-bound review manifest."
