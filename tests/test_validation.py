from pathlib import Path
from types import SimpleNamespace
from jee_pyq_pipeline.models import Question
from jee_pyq_pipeline.extract import (
    extract, _assets, _parse_answer, _split_options, _split_source_sections,
    _page_words, _question_start, _lines, _ocr_dpi, _crop_scan_regions,
    _clean_ocr_words, _join_word_tokens, _expected_subject_by_number, _column_split_x,
    _question_header_candidate, _infer_missing_top_question_header, _has_center_divider,
    _question_type_from_ranges, _sequence_header_gap,
)
from jee_pyq_pipeline.validate import validate
from jee_pyq_pipeline.cli import _build_batch

def cfg(tmp_path, expected=1, subject='Physics', solutions=False):
    return SimpleNamespace(
        answer_key=None,
        source_pdf=Path('paper.pdf'),
        page_range=(1,1),
        expected_question_count=expected,
        expected_question_numbers=tuple(f'{subject}:{n}' for n in range(1,expected+1)),
        source_has_solutions=solutions,
        source_solutions=None,
        subject=subject,
    )

def question(**overrides):
    source_hash='a'*64
    q=Question(
        'id-1',1,'A particle moves in a straight line with constant velocity.',
        {'A':'one','B':'two','C':'three','D':'four'},'A',[1],[0,0,120,18],
        {'source_sha256':source_hash,'source_document':'paper.pdf','source_release':'test'}
    )
    q.subject='Physics'
    q.question_type='MCQ'
    q.solution={
        'text':'Substitute the stated values into the relation to obtain the result.',
        'pages':[1],
        'source_reference':{'source_sha256':source_hash,'source_document':'paper.pdf'},
    }
    for k,v in overrides.items():
        setattr(q,k,v)
    return q

def codes(c, questions):
    return {i.code for i in validate(c,questions,1)}

def test_green_record(tmp_path):
    c=cfg(tmp_path,solutions=True)
    assert not validate(c,[question()],1)

def test_truncated_question(tmp_path):
    assert 'TRUNCATED_CONTENT' in codes(cfg(tmp_path),[question(text='short')])

def test_missing_required_image(tmp_path):
    assert 'MISSING_REQUIRED_IMAGE' in codes(cfg(tmp_path),[question(requires_figure=True)])

def test_malformed_options(tmp_path):
    assert 'MALFORMED_OPTIONS' in codes(cfg(tmp_path),[question(options={'A':'one'})])

def test_missing_answer(tmp_path):
    assert 'MISSING_OR_AMBIGUOUS_ANSWER' in codes(cfg(tmp_path),[question(answer=None)])

def test_duplicate_id(tmp_path):
    assert 'DUPLICATE_ID' in codes(cfg(tmp_path),[question(),question(id='id-1')])

def test_duplicate_source_number(tmp_path):
    c=cfg(tmp_path,expected=1)
    assert 'DUPLICATE_SOURCE_NUMBER' in codes(c,[question(),question(id='id-2')])

def test_count_mismatch(tmp_path):
    assert 'COUNT_MISMATCH' in {i.code for i in validate(cfg(tmp_path,2),[question()],1)}

def test_invalid_provenance(tmp_path):
    assert 'INVALID_PROVENANCE' in codes(cfg(tmp_path),[question(pages=[2])])

def test_notation_failure(tmp_path):
    assert 'UNPRESERVED_NOTATION' in codes(cfg(tmp_path),[question(text='A □ preserved?')])

def test_numeric_question():
    q=question(options={},answer='42',question_type='NUMERICAL')
    c=cfg(Path('.'))
    assert not validate(c,[q],1)

def test_answer_parser_preserves_multi_digit_and_option_answers():
    assert _parse_answer('42') == '42'
    assert _parse_answer('2') == '2'
    assert _parse_answer('(A) Only I is true') == 'A'

def test_split_side_by_side_options():
    text,options=_split_options([(1,'(A) one (B) two',[0,0,1,1]),(1,'(C) three (D) four',[0,0,1,1])])
    assert text==''
    assert options=={'A':'one','B':'two','C':'three','D':'four'}

def test_split_numeric_options():
    text,options=_split_options([(1,'(1) one (2) two',[0,0,1,1]),(1,'(3) three (4) four',[0,0,1,1])])
    assert text==''
    assert options=={'1':'one','2':'two','3':'three','4':'four'}

def test_source_answer_and_solution_split():
    qtext,qopts,answer,solution,qrows,srows,err=_split_source_sections([
        (1,'A statement (1) x (2) y (3) z (4) w',[0,0,1,1]),
        (1,'Answer: 2',[0,10,1,11]),
        (1,'Solution: Source solution text',[0,12,1,13]),
    ])
    assert answer=='2'
    assert solution=='Source solution text'
    assert qopts=={'1':'x','2':'y','3':'z','4':'w'}

def test_question_header_detection():
    assert _question_start('Question 1: Find the value') [1] == 1
    assert _question_start('Question1: Find the value') [1] == 1
    assert _question_start('Q1. Find the value') [1] == 1
    assert _question_start('1. Find the value') [1] == 1
    assert _question_start('1) Find the value') [1] == 1

def test_ocr_joining_preserves_question_and_option_markers():
    def word(text, index):
        return (10 + index * 18, 100, 24 + index * 18, 112, text, 0, 0, index)

    words = [word(text, index) for index, text in enumerate([
        "2", ".", "The", "value", "is", "(", "1", ")", "."
    ])]
    assert _join_word_tokens(words) == "2. The value is (1)."
    assert _question_start("2 . The value of x is equal to:")[1] == 2

    text, options = _split_options([
        (1, "( 1 ) one ( 2 ) two", [0, 0, 100, 12]),
        (1, "( 3 ) three ( 4 ) four", [0, 20, 100, 32]),
    ])
    assert text == ""
    assert options == {"1": "one", "2": "two", "3": "three", "4": "four"}


def test_tall_center_scan_divider_is_removed_before_column_detection():
    words = [
        (498, 150, 502, 850, "I", 0, 0, 0),
        (100, 200, 110, 212, "1", 0, 0, 1),
        (113, 200, 116, 212, ".", 0, 0, 2),
        (130, 200, 170, 212, "Left", 0, 0, 3),
    ]
    cleaned = _clean_ocr_words(words, 1000, 1000)
    assert not any(w[4] == "I" and w[0] >= 490 and w[2] <= 510 for w in cleaned)
    assert any(w[4] == "1" for w in cleaned)


def test_two_column_split_handles_center_rule_and_split_number_punctuation():
    def word(x0, y0, x1, y1, text, n):
        return (x0, y0, x1, y1, text, 0, 0, n)

    words = [word(498, 150, 502, 850, "I", 0)]
    n = 1
    for y, number, side, label in [
        (200, "1", 100, "Left"),
        (350, "2", 100, "Left"),
        (200, "3", 650, "Right"),
        (350, "4", 650, "Right"),
    ]:
        words.extend([
            word(side, y, side + 10, y + 12, number, n),
            word(side + 13, y, side + 16, y + 12, ".", n + 1),
            word(side + 30, y, side + 75, y + 12, label, n + 2),
            word(side + 82, y, side + 132, y + 12, "question", n + 3),
        ])
        n += 4
    words.extend([
        word(100, 800, 150, 812, "bottom", n),
        word(650, 800, 700, 812, "bottom", n + 1),
    ])
    words = _clean_ocr_words(words, 1000, 1000)
    lines = [_join_word_tokens(row) for row in _lines(words, 1000)]
    left_one = next(i for i, line in enumerate(lines) if line.startswith("1. Left"))
    left_two = next(i for i, line in enumerate(lines) if line.startswith("2. Left"))
    right_three = next(i for i, line in enumerate(lines) if line.startswith("3. Right"))
    right_four = next(i for i, line in enumerate(lines) if line.startswith("4. Right"))
    assert left_one < left_two < right_three < right_four


def test_midpoint_gutter_is_preferred_when_both_columns_have_question_headers():
    def word(x0, y0, x1, y1, text, n):
        return (x0, y0, x1, y1, text, 0, 0, n)

    words = []
    n = 0
    # Multiple large gaps in the central search band are deliberate distractors.
    for y, number in [(200, "1"), (350, "2"), (500, "3")]:
        words.extend([
            word(100, y, 110, y + 12, number, n),
            word(113, y, 116, y + 12, ".", n + 1),
            word(130, y, 360, y + 12, "left-column-question-text", n + 2),
            word(640, y, 650, y + 12, str(int(number) + 3), n + 3),
            word(653, y, 656, y + 12, ".", n + 4),
            word(670, y, 900, y + 12, "right-column-question-text", n + 5),
        ])
        n += 6
    assert _column_split_x(words, 1000) == 500


def test_midpoint_gutter_fallback_survives_unreadable_header_tokens():
    def word(x0, y0, x1, y1, text, n):
        return (x0, y0, x1, y1, text, 0, 0, n)

    words = []
    n = 0
    # Simulate OCR losing both printed question numbers while preserving the strong
    # two-column layout and center gutter from the source scan.
    for y in (200, 300, 400, 500):
        for idx in range(5):
            lx = 80 + idx * 35
            rx = 650 + idx * 35
            words.append(word(lx, y, lx + 22, y + 12, f"left{n}", n))
            n += 1
            words.append(word(rx, y, rx + 22, y + 12, f"right{n}", n))
            n += 1
    assert _column_split_x(words, 1000) == 500


def test_scan_pixel_detector_finds_true_midpoint_rule_not_cover_page_text(tmp_path):
    import fitz

    pdf = fitz.open()
    divided = pdf.new_page(width=1000, height=1200)
    divided.draw_line((500, 150), (500, 1100), color=(0.15, 0.30, 0.50), width=2)
    divided.insert_text((80, 200), "Left column question", fontsize=14)
    divided.insert_text((650, 200), "Right column question", fontsize=14)
    # Inspect the first page before adding another page; PyMuPDF can orphan a
    # previously held Page object when the document's page tree changes.
    assert _has_center_divider(divided) is True
    cover = pdf.new_page(width=1000, height=1200)
    cover.insert_text((100, 200), "A full-width cover page with instructions", fontsize=18)
    cover.insert_text((100, 260), "Many lines of one-column text without a center rule", fontsize=14)
    assert _has_center_divider(cover) is False
    pdf.close()


def test_midpoint_gutter_ignores_narrow_ocr_divider_fragments():
    def word(x0, y0, x1, y1, text, n):
        return (x0, y0, x1, y1, text, 0, 0, n)

    words = []
    n = 0
    for y in (200, 280, 360, 440):
        for idx in range(5):
            lx = 70 + idx * 34
            rx = 650 + idx * 34
            words.append(word(lx, y, lx + 22, y + 12, f"left{n}", n))
            n += 1
            words.append(word(rx, y, rx + 22, y + 12, f"right{n}", n))
            n += 1
    # OCR can turn a long vertical scan divider into many short narrow boxes.
    for j, y in enumerate(range(140, 340, 8)):
        words.append(word(499, y, 501, y + 5, "|", n + j))
    assert _column_split_x(words, 1000) == 500


def test_ocr_question_header_recovers_expected_number_after_leading_debris():
    match, number = _question_header_candidate(
        "1 2. The value of the series is:", [21, 2287, 982, 2418], 2479, 2
    )
    assert number == 2
    assert match is not None
    assert "The value" in "1 2. The value of the series is:"[match.end():]

    match, number = _question_header_candidate(
        "I 46. The displacement of a particle", [55, 318, 1245, 375], 2550, 46
    )
    assert number == 46
    match, number = _question_header_candidate(
        "| 50. The equivalent resistance", [1268, 824, 2495, 873], 2550, 50
    )
    assert number == 50
    match, number = _question_header_candidate(
        "| 75. Consider the dissociation equilibrium", [1232, 269, 2331, 319], 2479, 75
    )
    assert number == 75

    # A fractional option misread as “7. 7” is not in the number gutter.
    assert _question_header_candidate("7. 7", [343, 942, 866, 1010], 2479, 2) == (None, None)


def test_infer_missing_question_number_only_from_complete_top_of_column_block():
    raw = [
        # In the real scan, OCR misses the question number and the first
        # mathematical token begins inside the column instead of the number gutter.
        (3, "tan(A-B) expression and the statement", [334, 273, 1207, 315], "Mathematics"),
        (3, "then", [149, 335, 400, 370], "Mathematics"),
        (3, "(1) choice one", [149, 480, 600, 515], "Mathematics"),
        (3, "Ans. (1)", [149, 771, 317, 848], "Mathematics"),
        (3, "Sol. Rearranging the stated relation", [149, 842, 900, 880], "Mathematics"),
        (3, "5. Let z be a complex number", [149, 1726, 1207, 1874], "Mathematics"),
        (3, "Ans. (2)", [149, 2110, 300, 2140], "Mathematics"),
        (3, "Sol. Replacing the stated value gives the result.", [149, 2145, 900, 2180], "Mathematics"),
        (3, "6. Find the next value", [149, 2250, 900, 2290], "Mathematics"),
    ]
    assert _infer_missing_top_question_header(
        raw, 0, 4, {3: (2479.0, 3508.0)}, {4: "Mathematics", 5: "Mathematics", 6: "Mathematics"}
    ) is True
    # A continuation line from Q4 must not be mistaken for missing Q5 merely
    # because Q4 and the real Q5 both have Answer/Solution markers before Q6.
    assert _infer_missing_top_question_header(
        raw, 1, 5, {3: (2479.0, 3508.0)}, {4: "Mathematics", 5: "Mathematics", 6: "Mathematics"}
    ) is False

    # Without the complete Answer + Solution sequence, do not infer or shift numbering.
    incomplete = raw[:3] + raw[5:]
    assert _infer_missing_top_question_header(
        incomplete, 0, 4, {3: (2479.0, 3508.0)}, {4: "Mathematics", 5: "Mathematics"}
    ) is False


def test_unique_expected_printed_numbers_define_subject_mapping():
    assert _expected_subject_by_number({
        "Mathematics:1", "Physics:26", "Chemistry:51"
    }) == {1: "Mathematics", 26: "Physics", 51: "Chemistry"}
    assert _expected_subject_by_number({
        "Physics:1", "Chemistry:1", "Mathematics:1"
    }) == {}


def test_ocr_page_fallback():
    class FakePage:
        def __init__(self):
            self.ocr_calls=0
            self.rect=SimpleNamespace(width=100,height=100)
        def get_images(self, full=True):
            return []
        def get_image_info(self, xrefs=True):
            return []
        def get_text(self, kind='text', textpage=None):
            if kind == 'words' and textpage is None:
                return []
            return [(0,0,20,10,'Physics',0,0,0)]
        def get_textpage_ocr(self, **kwargs):
            self.ocr_calls += 1
            assert kwargs == {'language':'eng','dpi':200,'full':True}
            return object()
    page=FakePage()
    words,used_ocr=_page_words(page)
    assert used_ocr is True
    assert words[0][4] == 'Physics'
    assert page.ocr_calls == 1

def test_end_to_end_source_pdf(tmp_path):
    import fitz

    pdf_path = tmp_path / 'paper.pdf'
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    lines = [
        'Physics',
        'Question 1:',
        'A particle moves in a straight line with constant velocity.',
        '(1) one',
        '(2) two',
        '(3) three',
        '(4) four',
        'Answer: 2',
        'Solution: Substitute the given values into the relation to find the required quantity.',
        '7. This is a derivation line, not another question.',
        'Question 2:',
        'Calculate the source value.',
        'Answer: 42',
        'Solution: Rearranging the stated relation gives the required value.',
    ]
    y=40
    for line in lines:
        page.insert_text((40,y),line,fontsize=11)
        y += 24
    doc.save(pdf_path)
    doc.close()

    cfg = SimpleNamespace(
        source_pdf=pdf_path,
        release='test',
        exam='JEE-MAIN',
        year=2026,
        session='Test',
        paper='Test',
        subject='Physics',
        page_range=(1,1),
        expected_question_count=2,
        expected_question_numbers=('Physics:1','Physics:2'),
        source_has_solutions=True,
        source_zip=None,
        review_manifest=None,
    )
    questions, assets, extraction_issues, page_count = extract(cfg, tmp_path / 'assets')
    assert page_count == 1
    assert not extraction_issues
    assert [(q.subject,q.source_question_number,q.question_type,q.answer) for q in questions] == [
        ('Physics',1,'MCQ','2'),
        ('Physics',2,'NUMERICAL','42'),
    ]
    assert all(q.solution and q.solution['text'] for q in questions)
    assert '7. This is a derivation line, not another question.' in questions[0].solution['text']
    assert questions[0].options == {'1':'one','2':'two','3':'three','4':'four'}

    # Extraction may be structurally clean, but it must not be marked source-verified
    # or emit IMPORT_READY until a complete per-question review manifest is supplied.
    batch_dir = tmp_path / 'batch'
    status = _build_batch(cfg, batch_dir, timeout_seconds=60)
    assert status == 'REVIEW_REQUIRED'
    assert not (batch_dir / 'IMPORT_READY.json').exists()
    report = __import__('json').loads((batch_dir / 'validation-report.json').read_text(encoding='utf-8'))
    assert report['status'] == 'REVIEW_REQUIRED'
    assert report['review_gate']['status'] == 'PENDING'
    assert report['counts']['review_required'] == 2
    assert (batch_dir / 'review-manifest-template.json').is_file()


def test_full_page_scan_is_not_emitted_as_question_image(tmp_path):
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=200, height=300)
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 200, 300), 0)
    pix.clear_with(255)
    page.insert_image(page.rect, pixmap=pix)
    assets = _assets(page, 1, tmp_path / 'assets', 'b' * 64)
    assert assets == []
    doc.close()


def test_placeholder_record_is_quarantined():
    q = question(text='Question 1 (Physics): Validated source statement with mathematical precision.')
    q.solution = {
        'text':'Step-by-step mathematical proof...',
        'pages':[1],
        'source_reference':{'source_sha256':'a'*64,'source_document':'paper.pdf'},
    }
    found = codes(cfg(Path('.'), solutions=True), [q])
    assert 'PLACEHOLDER_CONTENT' in found


def test_legitimate_option_reference_is_not_misclassified_as_placeholder():
    q = question()
    q.solution = {
        'text':'Option A is correct because it satisfies the given condition.',
        'pages':[1],
        'source_reference':{'source_sha256':'a'*64,'source_document':'paper.pdf'},
    }
    assert 'PLACEHOLDER_CONTENT' not in codes(cfg(Path('.'), solutions=True), [q])


def test_invalid_source_lineage_is_rejected():
    q = question(provenance={'source_sha256':'a','source_document':'other.pdf'})
    assert 'INVALID_SOURCE_LINEAGE' in codes(cfg(Path('.')), [q])



def test_sol_period_marker_is_split_from_source_solution():
    qtext,qopts,answer,solution,qrows,srows,err=_split_source_sections([
        (1,'A statement with four options',[0,0,100,12]),
        (1,'(1) one (2) two (3) three (4) four',[0,20,100,32]),
        (1,'Ans. (3)',[0,40,80,52]),
        (1,'Sol. x + 2 = 5, so x = 3.',[0,60,150,72]),
    ])
    assert answer == '3'
    assert qopts == {'1':'one','2':'two','3':'three','4':'four'}
    assert solution == 'x + 2 = 5, so x = 3.'
    assert err is None


def test_two_column_question_rows_are_kept_in_column_order():
    def word(x0,y0,x1,y1,text,n):
        return (x0,y0,x1,y1,text,0,0,n)
    words = [
        word(100,100,120,115,'1.',0), word(130,100,180,115,'Left',1),
        word(190,100,250,115,'column',2), word(260,100,330,115,'question',3),
        word(100,200,120,215,'2.',4), word(130,200,180,215,'Left',5),
        word(190,200,250,215,'column',6), word(260,200,330,215,'second',7),
        word(650,100,670,115,'3.',8), word(680,100,735,115,'Right',9),
        word(745,100,805,115,'column',10), word(815,100,885,115,'question',11),
        word(650,200,670,215,'4.',12), word(680,200,735,215,'Right',13),
        word(745,200,805,215,'column',14), word(815,200,885,215,'second',15),
    ]
    lines = [' '.join(item[4] for item in row) for row in _lines(words,1000)]
    assert lines == [
        '1. Left column question',
        '2. Left column second',
        '3. Right column question',
        '4. Right column second',
    ]


def test_scan_crop_helper_produces_separate_bounded_question_and_solution_regions(tmp_path):
    import fitz
    pdf = fitz.open()
    page = pdf.new_page(width=1000,height=1400)
    pix = fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,1000,1400),0)
    pix.clear_with(255)
    page.insert_image(page.rect,pixmap=pix)
    block = {
        'subject':'Physics','number':1,'pages':{1},
        'rows':[
            (1,'1. Question stem',[100,200,450,230]),
            (1,'Ans. (2)',[100,500,200,530]),
            (1,'Sol. source explanation',[100,560,500,590]),
        ],
    }
    next_block = {
        'subject':'Physics','number':2,'pages':{1},
        'rows':[(1,'2. Next question',[100,800,450,830])],
    }
    asset_dir=tmp_path/'assets'
    question_assets=_crop_scan_regions(
        pdf,block,[block['rows'][0]],[block,next_block],0,asset_dir,'a'*64,
        'question',{1:72}
    )
    solution_assets=_crop_scan_regions(
        pdf,block,[block['rows'][2]],[block,next_block],0,asset_dir,'a'*64,
        'solution',{1:72}
    )
    assert len(question_assets)==1
    assert len(solution_assets)==1
    for asset in question_assets+solution_assets:
        image_path=tmp_path/asset.path
        assert image_path.is_file()
        image=fitz.Pixmap(str(image_path))
        assert image.width < 1000 and image.height < 1400
        assert asset.bounds[2]-asset.bounds[0] < 850
    assert question_assets[0].bounds[0] >= 30
    assert question_assets[0].bounds[2] < 500
    assert question_assets[0].bounds[3] < 500
    assert solution_assets[0].bounds[1] < 560
    assert solution_assets[0].bounds[3] < 800
    pdf.close()


def test_scan_ocr_dpi_matches_embedded_scan_resolution():
    import fitz
    pdf=fitz.open()
    page=pdf.new_page(width=200,height=300)
    pix=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,200,300),0)
    pix.clear_with(255)
    page.insert_image(page.rect,pixmap=pix)
    assert _ocr_dpi(page) == 72
    pdf.close()


def test_solution_continuation_across_columns_uses_separate_narrow_crops(tmp_path):
    import fitz

    pdf=fitz.open()
    page=pdf.new_page(width=1000,height=1200)
    pix=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,1000,1200),0)
    pix.clear_with(255)
    page.insert_image(page.rect,pixmap=pix)

    block={
        'subject':'Mathematics','number':2,'pages':{1},
        'rows':[
            (1,'2. Question stem',[100,300,430,330]),
            (1,'Ans. (2)',[100,450,180,470]),
            (1,'Sol. left-column working',[100,480,450,500]),
            (1,'right-column solution continuation',[600,100,900,120]),
        ],
    }
    next_block={
        'subject':'Mathematics','number':3,'pages':{1},
        'rows':[(1,'3. Next question',[600,200,900,230])],
    }
    assets=_crop_scan_regions(
        pdf,block,[block['rows'][2],block['rows'][3]],
        [block,next_block],0,tmp_path/'assets','b'*64,'solution',{1:72}
    )
    assert len(assets)==2
    left=[asset for asset in assets if asset.bounds[0]<500]
    right=[asset for asset in assets if asset.bounds[0]>=500]
    assert len(left)==1 and len(right)==1
    assert left[0].bounds[2] < 500
    assert right[0].bounds[3] < 200
    for asset in assets:
        image=fitz.Pixmap(str(tmp_path/asset.path))
        assert image.width < 500
        assert image.height < 250
    pdf.close()


def test_infer_missing_top_question_when_ocr_misses_sol_label():
    raw = [
        (3, "tan(A-B) expression continues", [334, 273, 1207, 315], "Mathematics"),
        (3, "Ans. (1)", [148, 771, 317, 848], "Mathematics"),
        (3, "| tan A - tan B = relation", [21, 842, 887, 930], "Mathematics"),
        (3, "5. Let z be a complex number", [149, 1726, 1207, 1874], "Mathematics"),
    ]
    assert _infer_missing_top_question_header(
        raw, 0, 4, {3: (2479.0, 3508.0)}, {4: "Mathematics", 5: "Mathematics"}
    ) is True


def test_numbered_answer_row_is_not_a_question_header():
    # The source prints "10. Ans. ()" in the solution column before the actual
    # Q10 stem on the next page. Do not consume the expected Q10 number here.
    bounds_right_column = [1273.37, 1662.0, 1524.29, 1703.0]
    assert _question_header_candidate(
        "10. Ans. ()", bounds_right_column, 2479.0, 10
    ) == (None, None)
    assert _question_header_candidate(
        "I 10. Ans. ()", bounds_right_column, 2479.0, 10
    ) == (None, None)

    bounds_left_column = [148.95, 272.0, 1208.63, 314.0]
    match, number = _question_header_candidate(
        "10. If alpha, beta are the roots of the equation",
        bounds_left_column,
        2479.0,
        10,
    )
    assert match is not None
    assert number == 10


def test_infer_q4_boundary_from_actual_source_ocr_noise():
    # Reproduces the 28 Jan Shift 1 source scan: Q4's equation is at the top
    # of the left column, its number is OCR'd as "4 If" without punctuation,
    # and the same OCR pass reads "Ans." / "Sol." as "1 Ans." / "Sol,".
    raw = [
        (3, "eee ee ee ee ee ee eee ee", [20.99, 0.0, 1189.64, 30.0], "Mathematics"),
        (3, "el) tan(A-B A eg i ‘ [0.5],", [325.9, 268.0, 1207.63, 389.0], "Mathematics"),
        (3, "—", [455.86, 298.0, 478.85, 300.0], "Mathematics"),
        (3, "4 If A, B, C", [147.95, 313.0, 980.7, 352.0], "Mathematics"),
        (3, "then", [264.92, 419.0, 342.9, 452.0], "Mathematics"),
        (3, "1 Ans. (1)", [20.99, 769.0, 316.9, 810.0], "Mathematics"),
        (3, "Sol, 1", [149.95, 879.0, 950.71, 913.0], "Mathematics"),
        (3, "5. Let be complex number such that | 6 | 5",
            [148.95, 1725.0, 1206.63, 1767.0], "Mathematics"),
    ]
    expected_subject_by_number = {4: "Mathematics", 5: "Mathematics"}
    assert _infer_missing_top_question_header(
        raw,
        0,
        4,
        {3: (2479.0, 3508.0)},
        expected_subject_by_number,
    ) is False
    assert _infer_missing_top_question_header(
        raw,
        1,
        4,
        {3: (2479.0, 3508.0)},
        expected_subject_by_number,
    ) is True


def test_answer_marker_tolerates_leading_scan_noise():
    parsed = _split_source_sections([
        (1, "A statement with four options", [100, 100, 400, 120]),
        (1, "] Ans. (3)", [100, 140, 180, 160]),
        (1, "Sol. x + 2 = 5, so x = 3.", [100, 180, 400, 200]),
    ])
    assert parsed[2] == "3"
    assert parsed[3] == "x + 2 = 5, so x = 3."


def test_infer_missing_question_after_noisy_answer_marker():
    raw = [
        (4, "Let S be the set of digits and x be the count", [149, 269, 1207, 319], "Mathematics"),
        (4, "] Ans. (3)", [21, 1021, 317, 1061], "Mathematics"),
        (4, "Sol. Counting the cases gives the required relation.", [150, 1095, 639, 1176], "Mathematics"),
        (4, "8. Let S= {x^2 + bx + c: ...}", [149, 1817, 1207, 1882], "Mathematics"),
    ]
    assert _infer_missing_top_question_header(
        raw, 0, 7, {4: (2479.0, 3508.0)}, {7: "Mathematics", 8: "Mathematics"}
    ) is True


def test_ocr_question_header_comma_separator():
    assert _question_start("20, Let y = y(x) be the solution of the differential equation")[1] == 20
    match, number = _question_header_candidate(
        "20, Let y = y(x) be the solution of the differential equation",
        [21, 2238, 1208, 2334], 2479, 20
    )
    assert number == 20
    assert match is not None
    assert "Let y" in "20, Let y = y(x) be the solution of the differential equation"[match.end():]


def test_ocr_question_header_comma_with_prefix_noise():
    match, number = _question_header_candidate(
        ", 22. For some theta > 0, let the eccentricity", [21, 278, 1208, 349], 2479, 22
    )
    assert number == 22
    assert match is not None


def test_explicit_question_type_ranges_are_source_grounded():
    ranges=((1,20,'MCQ'),(21,25,'NUMERICAL'),(26,45,'MCQ'),
            (46,50,'NUMERICAL'),(51,70,'MCQ'),(71,75,'NUMERICAL'))
    assert _question_type_from_ranges(1,ranges) == 'MCQ'
    assert _question_type_from_ranges(20,ranges) == 'MCQ'
    assert _question_type_from_ranges(21,ranges) == 'NUMERICAL'
    assert _question_type_from_ranges(25,ranges) == 'NUMERICAL'
    assert _question_type_from_ranges(26,ranges) == 'MCQ'
    assert _question_type_from_ranges(45,ranges) == 'MCQ'
    assert _question_type_from_ranges(46,ranges) == 'NUMERICAL'
    assert _question_type_from_ranges(50,ranges) == 'NUMERICAL'
    assert _question_type_from_ranges(51,ranges) == 'MCQ'
    assert _question_type_from_ranges(70,ranges) == 'MCQ'
    assert _question_type_from_ranges(71,ranges) == 'NUMERICAL'
    assert _question_type_from_ranges(75,ranges) == 'NUMERICAL'
    assert _question_type_from_ranges(76,ranges) is None


def test_configured_question_type_ranges_reject_overlap(tmp_path):
    import json
    from jee_pyq_pipeline.config import load
    value={
        'source_pdf':'paper.pdf','release':'test-release','exam':'JEE-MAIN','year':2026,
        'session':'Session 1','paper':'Paper 1','subject':'PCM','page_range':[1,1],
        'expected_question_count':3,
        'expected_question_numbers':['Mathematics:1','Mathematics:2','Mathematics:3'],
        'source_has_solutions':True,
        'question_type_ranges':[
            {'start':1,'end':2,'type':'MCQ'},
            {'start':2,'end':3,'type':'NUMERICAL'}
        ]
    }
    path=tmp_path/'config.json'
    path.write_text(json.dumps(value),encoding='utf-8')
    try:
        load(path)
    except ValueError as error:
        assert 'must not overlap' in str(error)
    else:
        raise AssertionError('overlapping question type bands must be rejected')


def test_configured_question_type_ranges_load(tmp_path):
    import json
    from jee_pyq_pipeline.config import load
    value={
        'source_pdf':'paper.pdf','release':'test-release','exam':'JEE-MAIN','year':2026,
        'session':'Session 1','paper':'Paper 1','subject':'PCM','page_range':[1,1],
        'expected_question_count':3,
        'expected_question_numbers':['Mathematics:1','Mathematics:2','Mathematics:3'],
        'source_has_solutions':True,
        'question_type_ranges':[
            {'start':1,'end':2,'type':'MCQ'},
            {'start':3,'end':3,'type':'NUMERICAL'}
        ]
    }
    path=tmp_path/'config.json'
    path.write_text(json.dumps(value),encoding='utf-8')
    config=load(path)
    assert config.question_type_ranges == ((1,2,'MCQ'),(3,3,'NUMERICAL'))


def test_sequence_header_gap_reports_missing_numbers_without_advancing_backwards():
    expected = list(range(1, 76))
    # Expected Q10 was unreadable; Q11 must still be detected, with Q10 left
    # as a blocking gap rather than absorbing the rest of the paper into Q9.
    assert _sequence_header_gap(expected, 9, 11) == (10, [10])
    assert _sequence_header_gap(expected, 10, 11) == (10, [])
    assert _sequence_header_gap(expected, 10, 9) is None
    assert _sequence_header_gap(expected, 10, 80) is None


def test_missing_numbered_header_does_not_swallow_all_later_source_questions(tmp_path):
    import fitz

    pdf_path = tmp_path / "paper-with-missing-q2-header.pdf"
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    lines = [
        "Physics",
        "Question 1: A particle moves with constant velocity; find its speed.",
        "(1) one",
        "(2) two",
        "(3) three",
        "(4) four",
        "Answer: 2",
        "Solution: Substitute the stated values into the relation to find the speed.",
        # Simulate an OCR-missed Q2 header/stem. This is Q3 as printed in source.
        "3. Calculate the source value from the stated data.",
        "Answer: 42",
        "Solution: Rearranging the stated relation gives the required value.",
    ]
    y = 45
    for line in lines:
        page.insert_text((40, y), line, fontsize=11)
        y += 38
    doc.save(pdf_path)
    doc.close()

    config = SimpleNamespace(
        source_pdf=pdf_path,
        release="test-gap-recovery",
        exam="JEE-MAIN",
        year=2026,
        session="Test",
        paper="Test",
        subject="Physics",
        page_range=(1, 1),
        expected_question_count=3,
        expected_question_numbers=("Physics:1", "Physics:2", "Physics:3"),
        source_has_solutions=True,
        source_zip=None,
        review_manifest=None,
    )
    questions, _assets_found, extraction_issues, page_count = extract(
        config, tmp_path / "assets"
    )
    assert page_count == 1
    assert [q.source_question_number for q in questions] == [1, 3]
    gap_issues = [i for i in extraction_issues if i.code == "MISSING_EXPECTED_QUESTION_HEADER"]
    assert len(gap_issues) == 1
    assert "2" in gap_issues[0].message
    assert "was not invented" in gap_issues[0].message
    assert questions[-1].text.startswith("Calculate the source value")
    # This paper is still not import-ready because Q2's source content is missing.
    assert "COUNT_MISMATCH" in {
        issue.code for issue in validate(config, questions, page_count)
    }

