#!/bin/bash
set -e

echo "=== JEE PYQ Pipeline - Representative Dry Run ==="
echo ""

# Step 1: Check PDF
echo "[1/5] Checking PDF..."
if [ ! -f "cEDaK5Wn5ILe4nOdotd6.pdf" ]; then
    echo "ERROR: PDF not found!"
    exit 1
fi
PDF_SIZE=$(stat -f%z "cEDaK5Wn5ILe4nOdotd6.pdf" 2>/dev/null || stat -c%s "cEDaK5Wn5ILe4nOdotd6.pdf")
echo "✓ PDF found ($(numfmt --to=iec $PDF_SIZE 2>/dev/null || echo $PDF_SIZE bytes))"
echo ""

# Step 2: Install dependencies
echo "[2/5] Installing dependencies..."
python -m pip install -e . -q
echo "✓ Dependencies installed"
echo ""

# Step 3: Generate config
echo "[3/5] Generating representative config..."
python - <<'PY'
import json, re
import fitz
from pathlib import Path

pdf = Path("cEDaK5Wn5ILe4nOdotd6.pdf")
doc = fitz.open(pdf)
text = "\n".join((p.get_text("text") or "") for p in doc)

markers = {
    "jee_main_2026": bool(re.search(r"JEE\s*Main\s*2026", text, re.I)),
    "jan_28": bool(re.search(r"28\s*(?:st|th)?\s*(?:January|Jan)", text, re.I)),
    "shift_1": bool(re.search(r"Shift\s*1|Morning", text, re.I)),
}

print(f"Identity markers: {markers}")
if not all(markers.values()):
    raise SystemExit(f"❌ Representative PDF identity gate failed: {markers}")

expected = (
    [f"Physics:{n}" for n in range(1, 26)] +
    [f"Chemistry:{n}" for n in range(1, 26)] +
    [f"Mathematics:{n}" for n in range(1, 26)]
)

cfg = {
    "source_pdf": str(pdf),
    "release": "2026-01",
    "exam": "JEE-MAIN",
    "year": 2026,
    "session": "Session 1 • Jan • 28 Jan • Shift 1",
    "paper": "Paper 1 • B.E./B.Tech",
    "subject": "PCM",
    "page_range": [1, len(doc)],
    "expected_question_count": 75,
    "expected_question_numbers": expected,
    "source_has_solutions": True
}

Path("representative-config.json").write_text(
    json.dumps(cfg, ensure_ascii=False, indent=2),
    encoding="utf-8"
)

print(f"✓ Config generated")
print(f"  - Pages: {len(doc)}")
print(f"  - Expected questions: {len(expected)} (25 Physics + 25 Chemistry + 25 Mathematics)")
doc.close()
PY
echo ""

# Step 4: Run extraction
echo "[4/5] Running extraction pipeline..."
rm -rf pipeline-output
PYTHONPATH=pipeline python -m jee_pyq_pipeline.cli \
  --config representative-config.json \
  --output pipeline-output \
  --max-pages 150 \
  --timeout-seconds 1200
echo ""

# Step 5: Check results
echo "[5/5] Validating results..."
if [ -f "pipeline-output/IMPORT_READY.json" ]; then
    echo "✓ IMPORT_READY.json found"
    cat pipeline-output/IMPORT_READY.json | python -m json.tool
    echo ""
fi

if [ -f "pipeline-output/validated.json" ]; then
    echo "✓ validated.json found"
    COUNT=$(python -c "import json; print(len(json.load(open('pipeline-output/validated.json'))))")
    echo "  - Total records: $COUNT"
fi

if [ -f "pipeline-output/validation-report.json" ]; then
    echo "✓ validation-report.json found"
    cat pipeline-output/validation-report.json | python -m json.tool | head -30
fi

echo ""
echo "=== Dry Run Complete ==="
echo "Results saved to: pipeline-output/"
