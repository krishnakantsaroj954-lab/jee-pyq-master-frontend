#!/usr/bin/env python3
"""Build a watermarked website export candidate; never bypass review gates."""
from __future__ import annotations
import hashlib, json
from pathlib import Path
from typing import Any

ROOT = Path("data/quarantine/2026-01-22-shift1")
SOURCE = ROOT / "jee_main_2026_01_22_shift1_FINAL_75Q.json"
MANIFEST = ROOT / "full-question-crop-manifest.json"
CANDIDATE = ROOT / "IMPORT_CANDIDATE.json"
BLOCKED = ROOT / "IMPORT_BLOCKED_REPORT.json"
READY = ROOT / "IMPORT_READY.json"
TRANSCRIPTIONS = ROOT / "manual-question-transcriptions.json"
SOLUTION_TRANSCRIPTIONS = ROOT / "manual-solution-transcriptions.json"

# Proposed tags derived from each visible source question; they are not official
# source labels and must be reviewed before the import gate can open.
CLASSIFICATION = {
1:("Vector Algebra","Vector projection and dot product"),
2:("Relations and Functions","Symmetric relation"),
3:("Integral Calculus","Area between curves"),
4:("Probability","Probability of divisibility"),
5:("Application of Derivatives","Minimum value of a function"),
6:("Three Dimensional Geometry","Shortest distance between skew lines"),
7:("Probability","Discrete probability distribution"),
8:("Sets, Relations and Functions","Modulus equation"),
9:("Integral Calculus","Integral-defined function"),
10:("Coordinate Geometry","Line and hyperbola"),
11:("Three Dimensional Geometry","Reflection of a point in a line"),
12:("Coordinate Geometry","Intersection of circles"),
13:("Matrices and Determinants","Determinant of a matrix polynomial"),
14:("Sets, Relations and Functions","Domain of a logarithmic function"),
15:("Integral Calculus","Greatest-integer function integral"),
16:("Binomial Theorem","Coefficient in binomial expansion"),
17:("Coordinate Geometry","Chord of a parabola"),
18:("Inverse Trigonometric Functions","Equation involving inverse tangent"),
19:("Differential Equations","First-order differential equation"),
20:("Sequences and Series","Arithmetic progression sums"),
21:("Complex Numbers and Quadratic Equations","Complex-number algebra"),
22:("Matrices and Determinants","Matrix identities and determinants"),
23:("Integral Calculus","Trigonometric integral"),
24:("Trigonometry","Trigonometric expression and inequality"),
25:("Permutations and Combinations","Counting triangles from points on sides"),
26:("Rotational Motion","Moment of inertia of touching spheres"),
27:("Atoms and Nuclei","Nuclear radius from alpha-particle scattering"),
28:("Electrostatics","Electric field of point charges"),
29:("Electromagnetic Induction","Induced emf in a moving-conductor loop"),
30:("Gravitation","Escape velocity and planetary density"),
31:("Current Electricity","Meter bridge and parallel resistance"),
32:("Kinematics","Projectile motion"),
33:("Mechanical Properties of Fluids","Fluid pressure and surface energy"),
34:("Semiconductor Electronics","Logic gates and LED circuit"),
35:("Gravitation","Net force due to masses at square corners"),
36:("Atoms and Nuclei","Mass defect and nuclear binding energy"),
37:("Kinetic Theory of Gases","Gas in a rotating tube"),
38:("Thermal Properties of Matter","Heat conduction through joined rods"),
39:("Ray Optics","Combined lens magnification; source labels this question Dropped"),
40:("Ray Optics","Refraction through a prism"),
41:("Thermodynamics","Adiabatic expansion of an ideal gas"),
42:("Electrostatics","Electric field and electric potential"),
43:("Electrostatics","Charged pendulum in an electric field"),
44:("Units and Measurements","Dimensional analysis"),
45:("Electromagnetic Induction","Faraday and Lenz laws for moving coaxial coils"),
46:("Waves","Doppler effect and sound"),
47:("Electromagnetic Waves","Wave propagation in a dielectric medium"),
48:("Ray Optics","Refraction at a spherical surface"),
49:("Rotational Motion","Moment of inertia of discs"),
50:("Electromagnetic Induction","Energy stored in an inductor"),
51:("Coordination Compounds","Unpaired electrons in low-spin complexes"),
52:("Chemical Bonding and Molecular Structure","Formal charges in HNO3"),
53:("Alcohols, Phenols and Ethers","Reimer-Tiemann reaction of phenol"),
54:("Atomic Structure","Bohr energy-level excitation"),
55:("p-Block Elements","Nitrogen-family chemistry and ionisation enthalpy"),
56:("Some Basic Concepts of Chemistry","Stoichiometry of aluminium and hydrochloric acid"),
57:("Solutions","Henry law and gas solubility"),
58:("d- and f-Block Elements","Transition-metal chemistry and complex formation"),
59:("Haloalkanes and Haloarenes","Nucleophilic substitution of bromomethane"),
60:("Thermodynamics","Reversible and irreversible isothermal work"),
61:("Hydrocarbons","Electrophilic aromatic substitution and directing effects"),
62:("Chemical Kinetics","Rate of a first-order reaction"),
63:("Aldehydes, Ketones and Carboxylic Acids","Carbonyl reagents and named reactions"),
64:("Classification of Elements and Periodicity in Properties","Periodic trends in hydrides and halogens"),
65:("Biomolecules","Sucrose hydrolysis and optical rotation"),
66:("Amines","Amine formation and diazotisation sequence"),
67:("Haloalkanes and Haloarenes","SN1 reaction rates"),
68:("Chemical Bonding and Molecular Structure","Lewis acid/base character and hybridisation"),
69:("Haloalkanes and Haloarenes","Bond character in chlorobenzene"),
70:("Solutions","Henry law constant"),
71:("Hydrocarbons","Bromination of a cycloalkane"),
72:("Electrochemistry","Cell emf and reaction quotient"),
73:("Chemical Kinetics","Arrhenius equation"),
74:("Practical Chemistry","Halogen detection and Carius method"),
75:("Chemical Equilibrium","Gas dissociation and Gibbs energy"),
}

def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def main() -> int:
    from watermark_images import build as watermark_build
    data = read(SOURCE)
    manifest = read(MANIFEST)
    transcriptions = read(TRANSCRIPTIONS)
    solution_transcriptions = read(SOLUTION_TRANSCRIPTIONS)
    wm = watermark_build(ROOT, "JEE PYQ Master")
    issues: list[dict[str, Any]] = []
    questions = data.get("questions", [])
    manual_texts = transcriptions.get("transcriptions", {})
    manual_solutions = solution_transcriptions.get("transcriptions", {})
    applied_transcriptions = 0
    applied_solution_transcriptions = 0
    for question in questions:
        number = str(question.get("question_number", ""))
        entry = manual_texts.get(number)
        flags = list(question.get("quality_flags") or [])
        if isinstance(entry, dict) and str(entry.get("question_text") or "").strip():
            question.setdefault("question_text_ocr_existing", question.get("question_text"))
            question["question_text"] = entry["question_text"]
            question["question_text_review_status"] = entry.get("status", "MANUAL_TRANSCRIPTION_PRESENT")
            question["question_text_review_note"] = entry.get("scope", "Question stem transcription only; solutions/provenance remain review-required.")
            applied_transcriptions += 1
            if "math_ocr_requires_review" in flags:
                flags.remove("math_ocr_requires_review")
                flags.append("solution_math_ocr_requires_review")
        solution_entry = manual_solutions.get(number)
        if isinstance(solution_entry, dict) and str(solution_entry.get("solution_text") or "").strip():
            question.setdefault("solution_text_ocr_existing", question.get("solution_text"))
            question["solution_text"] = solution_entry["solution_text"]
            question["solution_text_review_status"] = solution_entry.get("status", "MANUAL_SOLUTION_TRANSCRIPTION_PRESENT")
            question["solution_text_review_note"] = solution_entry.get("scope", "Printed-solution transcription; source provenance remains review-required.")
            applied_solution_transcriptions += 1
            if "math_ocr_requires_review" in flags:
                flags.remove("math_ocr_requires_review")
            if "solution_math_ocr_requires_review" in flags:
                flags.remove("solution_math_ocr_requires_review")
            if "solution_text_ocr_missing_but_image_attached" in flags:
                flags.remove("solution_text_ocr_missing_but_image_attached")
        question["quality_flags"] = flags
    crops = {int(x["question_number"]): x for x in manifest.get("question_crops", [])}
    if len(questions) != 75:
        issues.append({"scope":"dataset","issue":f"Expected 75 question records; found {len(questions)}"})
    if set(crops) != set(range(1,76)):
        issues.append({"scope":"images","issue":"Manifest must contain question crops 1..75"})
    if wm.get("source_image_count") != 125:
        issues.append({"scope":"watermark","issue":f"Expected 125 watermarked images; got {wm.get('source_image_count')}"})
    if data.get("paper",{}).get("source_sha256") != manifest.get("source_pdf_sha256"):
        issues.append({"scope":"provenance","issue":"JSON source SHA does not match the crop manifest"})
    # Official source match is still explicitly unverified in source metadata.
    issues.append({"scope":"provenance","issue":"Official-original match/publication rights were not independently verified"})

    def branded_path(original: str | None) -> str | None:
        if not original:
            return None
        p = Path(original)
        try:
            rel = p.relative_to("images")
        except ValueError:
            issues.append({"scope":"image_path","path":str(original),"issue":"Path is not under images/"})
            return None
        dest = ROOT / "images" / "watermarked" / rel
        if not dest.is_file():
            issues.append({"scope":"image_path","path":str(original),"issue":"Watermarked image derivative is missing"})
            return None
        return dest.relative_to(ROOT).as_posix()

    for q in questions:
        n = int(q.get("question_number", -1))
        crop = crops.get(n)
        if n not in CLASSIFICATION:
            issues.append({"question_number":n,"field":"chapter/topic","issue":"No topic mapping available"})
        else:
            q["chapter"], q["topic"] = CLASSIFICATION[n]
            q["classification_method"] = "inferred_from_source_question_text"
            q["classification_status"] = "PROPOSED_REVIEW_REQUIRED"

        if crop:
            q["question_image_path"] = "images/watermarked/" + str(crop["path"]).removeprefix("images/")
        for field in ("question_image_path","question_figure_image_path","solution_image_path",
                      "source_page_image_path","question_source_crop_path"):
            original = q.get(field)
            if field == "question_image_path" and crop:
                original = crop["path"]
            if original:
                q[field] = branded_path(original)

        dropped = q.get("question_status") == "Dropped" or q.get("correct_answer_status") == "dropped_in_source"
        if not str(q.get("question_text") or "").strip():
            issues.append({"question_number":n,"field":"question_text","issue":"Question text is empty"})
        if q.get("question_type") == "single_correct_mcq":
            opts = q.get("options")
            if not isinstance(opts,dict) or not all(k in opts and str(opts[k]).strip() for k in ("A","B","C","D")):
                issues.append({"question_number":n,"field":"options","issue":"MCQ lacks A/B/C/D option text"})
            elif not dropped and q.get("correct_answer") not in opts:
                issues.append({"question_number":n,"field":"correct_answer","issue":"Correct answer is not an A/B/C/D key"})
            elif not dropped and str(q.get("answer_text") or "").strip() != str(opts.get(q.get("correct_answer")) or "").strip():
                issues.append({"question_number":n,"field":"answer_text","issue":"Answer text does not match keyed option"})
        if not dropped and not str(q.get("correct_answer") or "").strip():
            issues.append({"question_number":n,"field":"correct_answer","issue":"Correct answer is missing"})
        if not dropped and not (q.get("solution_text") or q.get("solution_image_path")):
            issues.append({"question_number":n,"field":"solution","issue":"No solution text or solution image"})
        if not q.get("question_image_path") or not (ROOT / str(q.get("question_image_path",""))).is_file():
            issues.append({"question_number":n,"field":"question_image_path","issue":"Watermarked question image path is unresolved"})
        flags = q.get("quality_flags") or []
        if "math_ocr_requires_review" in flags or "solution_math_ocr_requires_review" in flags:
            issues.append({
                "question_number":n,
                "field":"solution_text",
                "issue":"Solution math OCR still requires source-by-source verification; the question stem has a separate manual-transcription overlay" if q.get("question_text_review_status") == "MANUALLY_TRANSCRIBED_FROM_QUESTION_CROP" else "Existing math OCR flag requires source-by-source verification"
            })
        if q.get("question_image_review_status") != "APPROVED":
            issues.append({"question_number":n,"field":"image_review","issue":"Question image is not formally approved"})
        if q.get("classification_status") != "APPROVED":
            issues.append({"question_number":n,"field":"chapter/topic","issue":"Proposed chapter/topic classification requires review"})

    for page in data.get("pages", []):
        for field in ("image_path","source_page_image_path"):
            if page.get(field):
                page[field] = branded_path(page[field])

    def resolve_watermark_output(value: str) -> Path | None:
        candidate = Path(value)
        possibilities = [candidate] if candidate.is_absolute() else [Path.cwd() / candidate, ROOT / candidate]
        return next((item for item in possibilities if item.is_file()), None)

    def verify_watermark_outputs(outputs: list[dict[str, Any]]) -> bool:
        if not outputs:
            return False
        for entry in outputs:
            output_path = resolve_watermark_output(str(entry.get("output_path") or ""))
            if output_path is None:
                return False
            if sha256(output_path) != entry.get("output_sha256"):
                return False
            if entry.get("output_sha256") == entry.get("source_sha256"):
                return False
        return True

    wm_valid = verify_watermark_outputs(wm.get("outputs", []))
    if not wm_valid:
        issues.append({"scope":"watermark","issue":"One or more watermark outputs failed checksum/change verification"})

    report = {
        "schema_version":"1.0.0",
        "paper_id":data.get("paper",{}).get("paper_id"),
        "source_pdf_sha256":data.get("paper",{}).get("source_sha256"),
        "source_pdf_bytes_verified_by_GitHub_runner":False,
        "question_count":len(questions),
        "question_crops_in_manifest":len(crops),
        "watermark_text":wm.get("watermark_text"),
        "watermarked_image_count":wm.get("source_image_count"),
        "watermark_checksums_verified":wm_valid,
        "answers_present":sum(bool(q.get("correct_answer")) for q in questions),
        "solutions_text_present":sum(bool(q.get("solution_text")) for q in questions),
        "solutions_image_present":sum(bool(q.get("solution_image_path")) for q in questions),
        "chapter_topic_proposals":sum(bool(q.get("chapter") and q.get("topic")) for q in questions),
        "question_text_manual_transcriptions":applied_transcriptions,
        "solution_text_manual_transcriptions":applied_solution_transcriptions,
        "solution_math_ocr_review_required":sum("solution_math_ocr_requires_review" in (q.get("quality_flags") or []) for q in questions),
        "blocking_issue_count":len(issues),
        "blocking_issues":issues,
        "status":"IMPORT_READY" if not issues else "BLOCKED_REVIEW_REQUIRED",
        "production_import":"NOT_PERFORMED",
        "notes":[
            "Watermarked derivatives are linked in this candidate; original images remain unchanged.",
            "Proposed chapter/topic metadata is inferred from question content, not printed source labels.",
            "Manual question-stem transcriptions are overlaid only from visually inspected question crops; the prior OCR stem is preserved in question_text_ocr_existing and question_ocr_raw.",
            "Nine printed solutions were manually transcribed from inspected solution crops/page images; original solution OCR is preserved in solution_text_ocr_existing and solution_ocr_raw.",
            "Solution math OCR review flags remain on the other records and are explicit import blockers. Do not import while this gate is blocked.",
            "Q39 remains Dropped with no invented answer.",
            "Watermark presence and file checksums were tested; question accuracy and source/publication rights are not certified by structural QA."
        ]
    }
    data["export_metadata"] = report
    CANDIDATE.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    BLOCKED.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    if issues:
        if READY.exists():
            READY.unlink()
    else:
        READY.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({
        "status":report["status"],
        "candidate":str(CANDIDATE),
        "blocked_report":str(BLOCKED),
        "watermarked_images":report["watermarked_image_count"],
        "blocking_issue_count":len(issues),
        "import_ready_file_exists":READY.exists(),
        "production_import":"NOT_PERFORMED"
    },indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
