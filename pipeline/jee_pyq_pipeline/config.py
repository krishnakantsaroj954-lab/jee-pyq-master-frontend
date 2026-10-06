from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path

REQUIRED = {
    "source_pdf", "release", "exam", "year", "session", "paper", "subject",
    "page_range", "expected_question_count", "expected_question_numbers",
    "subject_order", "source_has_solutions"
}

@dataclass(frozen=True)
class PaperConfig:
    source_pdf: Path
    release: str
    exam: str
    year: int
    session: str
    paper: str
    subject: str
    page_range: tuple[int, int]
    expected_question_count: int
    expected_question_numbers: tuple[str, ...]
    subject_order: tuple[str, ...]
    source_has_solutions: bool
    render_dpi: int = 180
    require_answers: bool = False
    source_zip: Path | None = None

def load(path: Path) -> PaperConfig:
    raw = json.loads(path.read_text(encoding="utf-8"))
    missing = REQUIRED - raw.keys()
    if missing:
        raise ValueError(f"Configuration missing required fields: {sorted(missing)}")
    pages = raw["page_range"]
    if not (isinstance(pages, list) and len(pages) == 2 and all(isinstance(x, int) and x > 0 for x in pages) and pages[0] <= pages[1]):
        raise ValueError("page_range must be [positive_start, positive_end]")
    count = raw["expected_question_count"]
    keys = raw["expected_question_numbers"]
    order = raw["subject_order"]
    if not isinstance(count, int) or count <= 0:
        raise ValueError("expected_question_count must be positive")
    if not isinstance(keys, list) or len(keys) != count or len(set(keys)) != count:
        raise ValueError("expected_question_numbers must contain exactly count unique Subject:Number keys")
    if not isinstance(order, list) or not order:
        raise ValueError("subject_order must be a non-empty list")
    allowed = {"Physics", "Chemistry", "Mathematics"}
    if any(s not in allowed for s in order):
        raise ValueError("subject_order contains an unsupported subject")
    if not isinstance(raw["source_has_solutions"], bool):
        raise ValueError("source_has_solutions must be boolean")
    base = path.parent
    def resolve(value):
        p = Path(value)
        return p.resolve() if p.is_absolute() else (base / p).resolve()
    return PaperConfig(
        source_pdf=resolve(raw["source_pdf"]),
        release=str(raw["release"]),
        exam=str(raw["exam"]),
        year=int(raw["year"]),
        session=str(raw["session"]),
        paper=str(raw["paper"]),
        subject=str(raw["subject"]),
        page_range=(pages[0], pages[1]),
        expected_question_count=count,
        expected_question_numbers=tuple(str(x) for x in keys),
        subject_order=tuple(order),
        source_has_solutions=raw["source_has_solutions"],
        render_dpi=int(raw.get("render_dpi", 180)),
        require_answers=bool(raw.get("require_answers", False)),
        source_zip=resolve(raw["source_zip"]) if raw.get("source_zip") else None,
    )
