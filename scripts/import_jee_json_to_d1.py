#!/usr/bin/env python3
"""Build an idempotent SQL batch for the existing JEE PYQ Master D1 schema."""
import hashlib, json, pathlib, sys
from collections import Counter

EXPECTED = 75
EXPECTED_SUBJECTS = {"Mathematics": 25, "Physics": 25, "Chemistry": 25}
EXAM_CODE, EXAM_NAME = "JEE_MAIN", "JEE Main"
SESSION_NAME = "April 8 Shift 2"
FILENAME = "jee_main_2026_04_08_shift_2_all_75_questions.json"

def s(value):
    return "'" + str(value).replace("'", "''") + "'"

def v(value):
    if value is None: return "NULL"
    if isinstance(value, bool): return "1" if value else "0"
    if isinstance(value, (int, float)): return repr(value)
    return s(value)

def add(out, sql):
    out.append(sql.rstrip().rstrip(";") + ";\n")

def build(input_path, output_path):
    raw = pathlib.Path(input_path).read_bytes()
    data = json.loads(raw)
    if not isinstance(data, list) or len(data) != EXPECTED:
        raise SystemExit(f"STOP: expected {EXPECTED} records")
    ids = [q.get("id") for q in data]
    if any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != EXPECTED:
        raise SystemExit("STOP: missing or duplicate IDs")
    counts = Counter(q.get("subject") for q in data)
    if dict(counts) != EXPECTED_SUBJECTS:
        raise SystemExit(f"STOP: subject counts mismatch: {dict(counts)}")
    for n, q in enumerate(data, 1):
        sol = q.get("solution")
        if q.get("year") != 2026 or q.get("date") != "2026-04-08" or q.get("shift") != 2:
            raise SystemExit(f"STOP: row {n} is not 2026-04-08 shift 2")
        if not q.get("question_text", "").strip() or not str(q.get("correct_answer", "")).strip():
            raise SystemExit(f"STOP: row {n} lacks question text or answer")
        if not isinstance(sol, dict) or not sol.get("solution_text", "").strip():
            raise SystemExit(f"STOP: row {n} lacks solution")
        if q.get("verification_status") != "verified" or sol.get("verification_status") != "verified":
            raise SystemExit(f"STOP: row {n} not marked verified")
        if q.get("question_type") == "MCQ":
            labels = [o.get("option_label") for o in q.get("options", [])]
            if len(labels) != 4 or set(labels) != {"A", "B", "C", "D"}:
                raise SystemExit(f"STOP: MCQ {q.get('id')} missing A-D options")

    out = ["-- Source SHA-256: " + hashlib.sha256(raw).hexdigest(),
           "-- Import of 75 JEE Main 2026-04-08 Shift 2 questions; idempotent; no schema changes.",
           "PRAGMA foreign_keys = ON;"]
    for name in EXPECTED_SUBJECTS:
        x = s(name)
        add(out, f"INSERT INTO subjects(name) SELECT {x} WHERE NOT EXISTS (SELECT 1 FROM subjects WHERE name={x})")
    add(out, "INSERT INTO years(year) SELECT 2026 WHERE NOT EXISTS (SELECT 1 FROM years WHERE year=2026)")
    ec, en = s(EXAM_CODE), s(EXAM_NAME)
    add(out, f"INSERT INTO exams(code,name) SELECT {ec},{en} WHERE NOT EXISTS (SELECT 1 FROM exams WHERE code={ec} OR name={en})")
    eid = f"(SELECT id FROM exams WHERE code={ec} OR name={en} ORDER BY CASE WHEN code={ec} THEN 0 ELSE 1 END LIMIT 1)"
    yid = "(SELECT id FROM years WHERE year=2026 LIMIT 1)"
    sn = s(SESSION_NAME)
    add(out, f"INSERT INTO sessions(exam_id,year_id,name) SELECT {eid},{yid},{sn} WHERE NOT EXISTS (SELECT 1 FROM sessions WHERE exam_id={eid} AND year_id={yid} AND name={sn})")

    for subject, chapter in sorted({(q["subject"], q["chapter"]) for q in data if q.get("chapter")}):
        sj, ch = s(subject), s(chapter)
        sid = f"(SELECT id FROM subjects WHERE name={sj} LIMIT 1)"
        add(out, f"INSERT INTO chapters(subject_id,name) SELECT {sid},{ch} WHERE NOT EXISTS (SELECT 1 FROM chapters WHERE subject_id={sid} AND name={ch})")
    for subject, chapter, topic in sorted({(q["subject"], q["chapter"], q["topic"]) for q in data if q.get("chapter") and q.get("topic")}):
        sj, ch, tp = s(subject), s(chapter), s(topic)
        cid = f"(SELECT c.id FROM chapters c JOIN subjects su ON su.id=c.subject_id WHERE su.name={sj} AND c.name={ch} LIMIT 1)"
        add(out, f"INSERT INTO topics(chapter_id,name) SELECT {cid},{tp} WHERE NOT EXISTS (SELECT 1 FROM topics WHERE chapter_id={cid} AND name={tp})")
    for subject, chapter, topic, subtopic in sorted({(q["subject"], q["chapter"], q["topic"], q["subtopic"]) for q in data if q.get("chapter") and q.get("topic") and q.get("subtopic")}):
        sj, ch, tp, st = map(s, (subject, chapter, topic, subtopic))
        tid = f"(SELECT t.id FROM topics t JOIN chapters c ON c.id=t.chapter_id JOIN subjects su ON su.id=c.subject_id WHERE su.name={sj} AND c.name={ch} AND t.name={tp} LIMIT 1)"
        add(out, f"INSERT INTO subtopics(topic_id,name) SELECT {tid},{st} WHERE NOT EXISTS (SELECT 1 FROM subtopics WHERE topic_id={tid} AND name={st})")

    for q in data:
        qid, sj = s(q["id"]), s(q["subject"])
        ch = s(q["chapter"]) if q.get("chapter") else None
        tp = s(q["topic"]) if q.get("topic") else None
        st = s(q["subtopic"]) if q.get("subtopic") else None
        sid = f"(SELECT id FROM subjects WHERE name={sj} LIMIT 1)"
        cid = f"(SELECT c.id FROM chapters c JOIN subjects su ON su.id=c.subject_id WHERE su.name={sj} AND c.name={ch} LIMIT 1)" if ch else "NULL"
        tid = f"(SELECT t.id FROM topics t JOIN chapters c ON c.id=t.chapter_id JOIN subjects su ON su.id=c.subject_id WHERE su.name={sj} AND c.name={ch} AND t.name={tp} LIMIT 1)" if ch and tp else "NULL"
        stid = f"(SELECT st.id FROM subtopics st JOIN topics t ON t.id=st.topic_id JOIN chapters c ON c.id=t.chapter_id JOIN subjects su ON su.id=c.subject_id WHERE su.name={sj} AND c.name={ch} AND t.name={tp} AND st.name={st} LIMIT 1)" if ch and tp and st else "NULL"
        src = q.get("source")
        srcjson = json.dumps(src, ensure_ascii=False, separators=(",", ":")) if src is not None else None
        srcurl = q.get("source_url") or (src.get("source_url") if isinstance(src, dict) else None)
        digest = hashlib.sha256(json.dumps(q, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        typ = "MCQ_SINGLE" if q.get("question_type") == "MCQ" else "NUMERICAL"
        cols = "id,exam_id,year_id,session_id,shift,paper,subject_id,chapter_id,topic_id,subtopic_id,question_text,question_type,difficulty,marks,negative_marks,correct_answer,solution,source,source_url,content_hash,is_demo"
        vals = ",".join([qid, eid, yid, f"(SELECT id FROM sessions WHERE exam_id={eid} AND year_id={yid} AND name={sn} LIMIT 1)",
                         s(str(q.get("shift", 2))), s(str(q.get("paper", 1))), sid, cid, tid, stid,
                         s(q["question_text"]), s(typ), s(q.get("difficulty") or "Unknown"),
                         v(q.get("marks", 4)), v(q.get("negative_marks", 1)), s(str(q["correct_answer"])),
                         s(q["solution"]["solution_text"]), v(srcjson), v(srcurl), s(digest), "0"])
        add(out, f"INSERT INTO questions({cols}) SELECT {vals} WHERE NOT EXISTS (SELECT 1 FROM questions WHERE id={qid})")

        for idx, opt in enumerate(q.get("options") or []):
            key, text = s(opt["option_label"]), v(opt.get("option_text"))
            add(out, f"INSERT INTO question_options(question_id,option_key,option_text,option_image_url,sort_order) SELECT {qid},{key},{text},NULL,{idx} WHERE NOT EXISTS (SELECT 1 FROM question_options WHERE question_id={qid} AND option_key={key})")
        soltext = s(q["solution"]["solution_text"])
        add(out, f"INSERT INTO solutions(question_id,solution_text,solution_type,sort_order) SELECT {qid},{soltext},'verified',0 WHERE NOT EXISTS (SELECT 1 FROM solutions WHERE question_id={qid} AND solution_text={soltext})")
        image = q.get("image")
        if isinstance(image, str) and image.strip():
            iu, alt = s(image.strip()), s("Question image for " + q["id"])
            add(out, f"INSERT INTO question_images(question_id,role,storage_provider,object_key,public_url,alt_text,mime_type,sort_order) SELECT {qid},'question','external',{iu},{iu},{alt},'image/png',0 WHERE NOT EXISTS (SELECT 1 FROM question_images WHERE question_id={qid} AND public_url={iu})")
        for tag in sorted(set(q.get("tags") or [])):
            tg = s(str(tag))
            add(out, f"INSERT INTO tags(name) SELECT {tg} WHERE NOT EXISTS (SELECT 1 FROM tags WHERE name={tg})")
            add(out, f"INSERT INTO question_tags(question_id,tag_id) SELECT {qid},(SELECT id FROM tags WHERE name={tg} LIMIT 1) WHERE NOT EXISTS (SELECT 1 FROM question_tags WHERE question_id={qid} AND tag_id=(SELECT id FROM tags WHERE name={tg} LIMIT 1))")

    all_ids = ",".join(s(i) for i in ids)
    add(out, f"INSERT INTO import_runs(filename,format,total_rows,valid_rows,invalid_rows,duplicate_rows,imported_rows,status) SELECT {s(FILENAME)},'json/jee-pyq-master-v1',{EXPECTED},{EXPECTED},0,0,(SELECT COUNT(*) FROM questions WHERE id IN ({all_ids})),'success'")
    path = pathlib.Path(output_path)
    path.write_text("\n".join(out), encoding="utf-8")
    print("SOURCE_SHA256=" + hashlib.sha256(raw).hexdigest())
    print(f"VALIDATION=PASS questions={len(data)} subjects={dict(counts)} options={sum(len(q.get('options') or []) for q in data)} solutions={len(data)} image_urls={sum(bool(q.get('image')) for q in data)} tag_links={sum(len(q.get('tags') or []) for q in data)}")
    print(f"SQL_BYTES={path.stat().st_size} SQL_STATEMENTS={sum(x.rstrip().endswith(';') for x in out)}")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: import_jee_json_to_d1.py INPUT.json OUTPUT.sql")
    build(sys.argv[1], sys.argv[2])
