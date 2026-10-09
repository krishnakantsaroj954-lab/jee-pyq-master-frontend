#!/usr/bin/env python3
"""Create per-question crops from reviewed Jan 22 Shift 1 page JPEGs.
Never edits question text, options, answers, or solution text.
"""
from pathlib import Path
from PIL import Image
import argparse, hashlib, json

SOURCE_PDF = "BPD4dLYdvGj7xm8cDL66.pdf"
SOURCE_SHA = "7d633fea3bf16857bc4c477d80b2a3eb2535603b54f665c3d683b777f02f52f3"
QUESTION_FIGURES = {
  7: (3, (562,169,965,231), "Probability distribution table in the question"),
  28: (9, (630,350,957,540), "Six-point charge diagram"),
  29: (10, (172,410,400,573), "Sliding rod and conducting loop diagram"),
  31: (10, (620,790,856,950), "Meter bridge circuit diagram"),
  34: (11, (630,1005,875,1173), "Logic-gate and LED circuit"),
  35: (12, (184,580,365,697), "Square with four corner masses"),
  37: (12, (600,935,855,1048), "Rotating gas-filled cylindrical tube"),
  38: (13, (105,925,430,1060), "Thermal-conduction rod network"),
  44: (15, (85,145,510,318), "List-I/List-II dimensions table"),
  45: (15, (585,90,790,280), "Three coaxial coils with current directions"),
  46: (15, (635,1030,875,1210), "Two loudspeakers and recorder positions"),
  52: (18, (100,843,242,965), "HNO3 Lewis structure with numbered atoms"),
  57: (19, (574,895,939,1185), "Four candidate graphs"),
  60: (20, (550,140,950,1001), "Thermodynamic process matching table"),
  61: (21, (326,730,485,820), "Substituted benzene structure shown in Statement I"),
  63: (21, (550,620,968,1014), "Reagents/reaction-name matching table"),
  66: (22, (558,570,964,857), "Four organic compound structures"),
  67: (23, (110,340,510,480), "Four substrate structures for SN1 comparison"),
  75: (24, (555,685,800,770), "Standard Gibbs-energy data table"),
}
SOLUTION_BLOCKS = {
  18: (6, (525,35,965,510), "Printed solution block for Q18"),
  27: (9, (45,850,500,1235), "Printed solution block for Q27, including explanatory scattering diagram"),
  32: (11, (525,35,965,470), "Printed solution block for Q32"),
  38: (13, (520,35,965,755), "Printed solution block for Q38"),
  45: (15, (520,55,965,580), "Printed solution block for Q45"),
  60: (21, (45,35,500,615), "Printed solution block for Q60"),
}

def sha256(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024), b""): h.update(chunk)
    return h.hexdigest()

def crop(root, page_no, box, dest):
    src=root/"images"/"pages"/f"page_{page_no:02d}.jpg"
    im=Image.open(src).convert("RGB")
    sx,sy=im.width/1024.0,im.height/1450.0
    x1,y1,x2,y2=box
    pad=4
    px1=max(0,int((x1-pad)*sx)); py1=max(0,int((y1-pad)*sy))
    px2=min(im.width,int((x2+pad)*sx)); py2=min(im.height,int((y2+pad)*sy))
    result=im.crop((px1,py1,px2,py2))
    dest.parent.mkdir(parents=True,exist_ok=True)
    result.save(dest,"JPEG",quality=95,optimize=True,progressive=True)
    return {"source_page":f"images/pages/page_{page_no:02d}.jpg",
            "source_bbox_preview":[round(px1/sx,2),round(py1/sy,2),round(px2/sx,2),round(py2/sy,2)],
            "native_bbox":[px1,py1,px2,py2],"width":result.width,"height":result.height,
            "bytes":dest.stat().st_size,"sha256":sha256(dest)}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--data-dir",required=True)
    args=ap.parse_args()
    root=Path(args.data_dir)
    json_path=root/"jee_main_2026_01_22_shift1_FINAL_75Q.json"
    data=json.loads(json_path.read_text(encoding="utf-8"))
    if data.get("paper",{}).get("source_sha256") != SOURCE_SHA:
        raise SystemExit("Source PDF SHA-256 mismatch; refusing to alter image paths.")
    questions=data.get("questions",[])
    if len(questions)!=75:
        raise SystemExit(f"Expected 75 questions, found {len(questions)}")
    nums={q.get("question_number") for q in questions}
    if nums!=set(range(1,76)):
        raise SystemExit("Question numbers not exactly 1..75; refusing to modify dataset.")

    crop_manifest={"schema_version":1,"source_pdf":SOURCE_PDF,"source_pdf_sha256":SOURCE_SHA,
      "coordinate_note":"Crops were generated from bundled full-page JPEGs using manually estimated boxes in 1024x1450 preview coordinates, scaled to the source JPEGs. They are question-specific best-effort crops and require visual review before production use. Original question text/options/answers/solutions were not edited.",
      "question_figures":[],"solution_crops":[]}
    question_paths={39:"images/questions/q039_question.jpg"}
    solution_paths={}
    for n,(page,box,description) in QUESTION_FIGURES.items():
        name=f"q{n:03d}_figure.jpg"
        dest=root/"images"/"questions"/name
        meta=crop(root,page,box,dest)
        crop_manifest["question_figures"].append({"question_number":n,"path":f"images/questions/{name}","description":description,**meta})
        question_paths[n]=f"images/questions/{name}"
    for n,(page,box,description) in SOLUTION_BLOCKS.items():
        name=f"q{n:03d}_solution.jpg"
        dest=root/"images"/"solutions"/name
        meta=crop(root,page,box,dest)
        crop_manifest["solution_crops"].append({"question_number":n,"path":f"images/solutions/{name}","description":description,**meta})
        solution_paths[n]=f"images/solutions/{name}"

    for q in questions:
        n=q["question_number"]
        q["question_image_path"]=question_paths.get(n)
        q["solution_image_path"]=solution_paths.get(n)
        if not q.get("source_page_image_path"):
            raise SystemExit(f"Question {n} is missing source_page_image_path")
    data["image_path_convention"]="Paths are relative to this dataset directory. question_image_path is null unless a question contains a relevant figure/table/graph; those paths target question-specific crops under images/questions/. Q39 remains Dropped and uses its existing question crop. solution_image_path is null unless the printed solution needs its own readable crop under images/solutions/. source_page_image_path always preserves the original full-page source image for provenance."
    data["database_notes"]["import_gate"]="Not production-ready. Review all OCR/transcription and every question/solution crop visually against the source page images before any import. No Worker/D1 import or deployment is performed by this pipeline."
    json_path.write_text(json.dumps(data,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    crop_path=root/"image-crop-manifest.json"
    crop_path.write_text(json.dumps(crop_manifest,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")

    paths=sorted((root/"images").rglob("*.jpg"))
    assets=[]
    for p in paths:
        rel=p.relative_to(root).as_posix()
        assets.append({"path":rel,"bytes":p.stat().st_size,"sha256":sha256(p),"mime_type":"image/jpeg"})
    if len(assets)!=50:
        raise SystemExit(f"Expected 50 image assets (24 pages + Q39 + 19 question crops + 6 solution crops), found {len(assets)}")
    old_manifest_path=root/"asset-manifest.json"
    old=json.loads(old_manifest_path.read_text(encoding="utf-8")) if old_manifest_path.exists() else {}
    manifest={"manifest_version":"1.1.0","paper_id":"jee-main-2026-01-22-s1",
      "dataset_json":json_path.name,"dataset_sha256":sha256(json_path),
      "source_pdf_sha256":SOURCE_SHA,"bundle_sha256":old.get("bundle_sha256"),
      "asset_count":len(assets),"assets_total_bytes":sum(a["bytes"] for a in assets),
      "assets":assets,"crop_manifest":"image-crop-manifest.json",
      "status":"QUESTION_SPECIFIC_CROPS_GENERATED_REVIEW_REQUIRED","production_import":"NOT_PERFORMED"}
    old_manifest_path.write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")

    readme="""# JEE Main 2026 — 22 January Shift 1 (Quarantined Dataset)

## Current status
- 75 question records remain in source order; Q39 remains present and marked Dropped without an invented answer.
- 24 original full-page source images are retained under images/pages/.
- Question-specific crops: 19 figure/table/graph crops plus the pre-existing Q39 question crop.
- Six printed-solution crops were created for questions whose solution text is missing/unreadable in the JSON.
- question_image_path and solution_image_path now point only to specific crops or null; source_page_image_path preserves the full-page source.
- All 50 JPEG assets are listed with SHA-256 values in asset-manifest.json; crop coordinates/metadata are in image-crop-manifest.json.

## Important review gate
The crop boxes were estimated from source-page previews and are not claimed to be perfect. Review each crop for cut-off labels, stray text, and correct question association, then review all OCR/transcription, options, answers, and solution text against the original PDF. Several dataset records remain incomplete or OCR-only. This is not production-ready and must stay under data/quarantine/.

No Cloudflare Worker/D1 import, production database change, or website deployment was performed. The repository still needs a separate reviewed frontend integration change.
"""
    (root/"README.md").write_text(readme,encoding="utf-8")
    (root/"README.txt").write_text(readme,encoding="utf-8")
    available={p.relative_to(root).as_posix() for p in paths}
    missing=[]
    for q in questions:
        for key in ("question_image_path","solution_image_path","source_page_image_path"):
            if q.get(key) and q[key] not in available: missing.append((q["question_number"],key,q[key]))
    if missing: raise SystemExit("Missing image references: "+repr(missing))
    print(json.dumps({"status":manifest["status"],"questions":len(questions),
      "question_specific_figures":len(QUESTION_FIGURES),"solution_crops":len(SOLUTION_BLOCKS),
      "q39_status":next(q.get("question_status") for q in questions if q["question_number"]==39),
      "assets":len(assets),"referenced_path_validation":"passed",
      "dataset_sha256":manifest["dataset_sha256"],"production_import":"NOT_PERFORMED"},indent=2))

if __name__=="__main__": main()
