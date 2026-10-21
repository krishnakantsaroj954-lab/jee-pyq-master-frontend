"""Unit tests for the source-aware Jan 22 Shift 1 crop boundary rules."""
from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "pipeline" / "build_jan22_full_question_crops.py"
SPEC = importlib.util.spec_from_file_location("jan22_crop_pipeline", SCRIPT)
assert SPEC and SPEC.loader
PIPE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PIPE)


def row(page: int, side: str, y: float, text: str, x0: float = 50, x1: float = 300) -> dict:
    return {"page": page, "side": side, "x0": x0, "y0": y, "x1": x1, "y1": y + 20, "text": text}


def test_answer_boundary_accepts_dropped_label_and_excludes_correct_answer() -> None:
    assert PIPE.is_answer_row(row(12, "R", 900, "Ans. (Dropped)"))
    assert PIPE.is_answer_row(row(2, "L", 800, "Ans. (3)"))
    assert not PIPE.is_answer_row(row(2, "L", 790, "Correct Ans. (2)"))


def test_header_recognition_is_number_specific_and_handles_ocr_debris() -> None:
    assert PIPE.header_candidate(row(23, "L", 1598, "i] 69. As compared with chlorocyclohexane", x0=8, x1=400), 69, 1736)
    assert PIPE.header_candidate(row(2, "L", 445, "5, Let f(x)=...", x0=100, x1=500), 5, 1736)
    assert not PIPE.header_candidate(row(2, "L", 445, "5, Let f(x)=...", x0=100, x1=500), 6, 1736)
    assert not PIPE.header_candidate(row(2, "R", 450, "Ans. (4)", x0=890, x1=980), 4, 1736)


def test_answer_mapping_requires_exactly_one_answer_between_headers() -> None:
    rows = []
    header_indices = {}
    for number in range(1, 76):
        header_indices[number] = len(rows)
        rows.append(row(2 + (number - 1) // 4, "L" if number % 2 else "R", number * 10, f"{number}. Example question"))
        rows.append(row(2 + (number - 1) // 4, "L" if number % 2 else "R", number * 10 + 5, "Ans. (Dropped)" if number == 39 else "Ans. (2)"))
    answers = PIPE.locate_answers(rows, header_indices)
    assert len(answers) == 75
    assert all(PIPE.is_answer_row(answers[n][1]) for n in range(1, 76))


def test_border_glyphs_are_not_used_as_question_content() -> None:
    assert not PIPE.meaningful_source_row(row(23, "R", 0, "—E——E——>EE—EEeo>——E————————————————= ==", x0=14, x1=860), 1736, 2456)
    assert not PIPE.meaningful_source_row(row(23, "R", 26, "1", x0=1716, x1=1725), 1736, 2456)
    assert PIPE.meaningful_source_row(row(23, "R", 189, "E. The C-Cl bond is formed using sp2 hybridised", x0=972, x1=1500), 1736, 2456)

def test_hosted_tesseract_q51_header_has_explicit_source_anchor() -> None:
    anchor = PIPE.MANUAL_HEADER_ANCHORS[51]
    assert anchor["page"] == 18
    assert anchor["side"] == "L"
    assert abs(anchor["y"] - 445.8) < 0.1
    assert "visually checked" in anchor["review_reason"]
