#!/usr/bin/env python3
"""Create a watermarked website-export candidate, never bypassing review gates."""
from __future__ import annotations
import json
from pathlib import Path
import sys

ROOT = Path("data/quarantine/2026-01-22-shift1")
SOURCE = ROOT / "jee_main_2026_01_22_shift1_FINAL_75Q.json"
MANIFEST = ROOT / "full-question-crop-manifest.json"
OUT = ROOT / "IMPORT_READY.json"
BLOCKED = ROOT / "IMPORT_BLOCKED_REPORT.json"

def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))

def main() -> int:
    sys.path.insert(0, str(Path("pipeline").resolve()))
    from watermark_images import build as watermark_build

    data = read(SOURCE)
    manifest = read(MANIFEST)
    wm = watermark_build(ROOT, "JEE PYQ Master")
    image_root = ROOT / "images"
    issues = []
    crops = {int(x["question_number"]): x for x in manifest.get("question_crops", [])}

    if len(data.get("questions", [])) != 75:
        issues.append({"scope": "dataset", "issue": "Expected exactly 75 question records"})
    if len(crops) != 75:
        issues.append({"scope": "images", "issue": "Expected exactly 75 manifest question crops"})

    def branded_path(original: str | None) -> str | None:
        if not original:
            return None
        p = Path(original)
        try:
            rel = p.relative_to("images")
        except ValueError:
            issues.append({"scope": "image_path", "path": original, "issue": "Path is not under images/"})
            return None
        target = image_root / "watermarked" / rel
        if not target.is_file():
            issues.append({"scope": "image_path", "path": original, "issue": "Watermarked image file missing"})
            return None
        return target.relative_to(ROOT).as_posix()

    # Relink the main question image directly to the manifest's crop for each number.
    for q in data.get("questions", []):
        n = int(q.get("question_number", -1))
        crop = crops.get(n)
        if crop:
            q["question_image_path"] = "images/watermarked/" + str(crop["path"]).removeprefix("images/")
        for field in ("question_image_path", "question_figure_image_path",
                      "solution_image_path", "source_page_image_path"):
            original = q.get(field)
            if field == "question_image_path" and crop:
                original = crop["path"]
            if original:
                q[field] = branded_path(original)
        dropped = q.get("question_status") == "Dropped" or q.get("correct_answer_status") == "dropped_in_source"
        if not q.get("question_text", "").strip():
            issues.append({"question_number": n, "field": "question_text", "issue": "Missing question text"})
        options = q.get("options")
        if q.get("question_type") == "single_correct_mcq":
            if not isinstance(options, dict) or not all(k in options and str(options[k]).strip() for k in ("A","B","C","D")):
                issues.append({"question_number": n, "field": "options", "issue": "MCQ does not have all non-empty A/B/C/D options"})
        if not dropped and not q.get("correct_answer"):
            issues.append({"question_number": n, "field": "correct_answer", "issue": "Missing correct answer"})
        if not dropped and not (q.get("solution_text") or q.get("solution_image_path")):
            issues.append({"question_number": n, "field": "solution", "issue": "No solution text or solution image"})
        if not q.get("question_image_path") or not (ROOT / str(q.get("question_image_path", ""))).is_file():
            issues.append({"question_number": n, "field": "question_image_path", "issue": "Question image path missing or unresolved"})
        # A human must explicitly review each crop and all extracted content before production.
        if q.get("question_image_review_status") != "APPROVED":
            issues.append({"question_number": n, "field": "human_review", "issue": "Question crop/content has not been marked APPROVED by a reviewer"})

    for page in data.get("pages", []):
        for field in ("image_path", "source_page_image_path"):
            if page.get(field):
                page[field] = branded_path(page[field])

    # Never call an unreviewed dataset import-ready. Preserve every source field and add
    # explicit build metadata to a candidate only after all quality/review gates pass.
    audit = {
        "schema_version": "1.0.0",
        "paper_id": data.get("paper", {}).get("paper_id"),
        "watermark_text": wm.get("watermark_text"),
        "watermark_status": "APPLIED_TO_IMAGE_DERIVATIVES",
        "watermarked_image_count": wm.get("source_image_count"),
        "source_images_modified": False,
        "dataset_source": SOURCE.name,
        "question_count": len(data.get("questions", [])),
        "question_crops_in_manifest": len(crops),
        "blocking_issue_count": len(issues),
        "blocking_issues": issues,
        "production_import": "NOT_PERFORMED",
        "status": "IMPORT_READY" if not issues else "BLOCKED_REVIEW_REQUIRED",
        "note": "Do not import while status is BLOCKED_REVIEW_REQUIRED. No answers, options, or solutions were invented.",
    }
    if not issues:
        data["export_metadata"] = audit
        OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if BLOCKED.exists():
            BLOCKED.unlink()
        print(json.dumps({"status": audit["status"], "output": str(OUT), "watermarked_images": wm["source_image_count"]}, indent=2))
        return 0

    if OUT.exists():
        OUT.unlink()
    BLOCKED.write_text(json.dumps({"audit": audit, "source_dataset": data}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": audit["status"], "blocked_report": str(BLOCKED), "watermarked_images": wm["source_image_count"], "blocking_issue_count": len(issues)}, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
