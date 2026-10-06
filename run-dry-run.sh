#!/bin/bash
set -euo pipefail

test -f "cEDaK5Wn5ILe4nOdotd6.pdf"

python - <<'PY'
import json
import fitz
from pathlib import Path

cfg_path = Path("representative-config.json")
cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
doc = fitz.open(cfg["source_pdf"])
cfg["page_range"] = [1, len(doc)]
cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Representative PDF pages: {len(doc)}")
doc.close()
PY

python -m pip install -e ".[test]" -q
rm -rf pipeline-output
PYTHONPATH=pipeline python -m pytest -q
PYTHONPATH=pipeline python -m jee_pyq_pipeline.cli \
  --config representative-config.json \
  --output pipeline-output \
  --max-pages 150

find pipeline-output -name "validation-report.json" -print -exec cat {} \;
find pipeline-output -name "IMPORT_READY.json" -print
