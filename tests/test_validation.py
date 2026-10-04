from pathlib import Path
from types import SimpleNamespace
from jee_pyq_pipeline.models import Question
from jee_pyq_pipeline.extract import extract, _split_options, _split_source_sections, _page_words
from jee_pyq_pipeline.validate import validate

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
    q=Question(
        'id-1',1,'Question content long enough to validate.',
        {'A':'one','B':'two','C':'three','D':'four'},'A',[1],[0,0,1,1],
        {'source_sha256':'a'}
    )
    q.subject='Physics'
    q.question_type='MCQ'
    q.solution={'text':'source solution text','pages':[1]} 
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

def test_ocr_page_fallback():
    class FakePage:
        def __init__(self):
            self.ocr_calls=0
        def get_text(self, kind='text', textpage=None):
            if kind == 'words' and textpage is None:
                return []
            return [(0,0,20,10,'Physics',0,0,0)]
        def get_textpage_ocr(self, **kwargs):
            self.ocr_calls += 1
            assert kwargs == {'language':'eng','dpi':250,'full':True}
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
        'A sample question with four source options.',
        '(1) one',
        '(2) two',
        '(3) three',
        '(4) four',
        'Answer: 2',
        'Solution: Source solution for question one.',
        'Question 2:',
        'Calculate the source value.',
        'Answer: 42',
        'Solution: Source solution for question two.',
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
    )
    questions, assets, extraction_issues, page_count = extract(cfg, tmp_path / 'assets')
    assert page_count == 1
    assert not extraction_issues
    assert [(q.subject,q.source_question_number,q.question_type,q.answer) for q in questions] == [
        ('Physics',1,'MCQ','2'),
        ('Physics',2,'NUMERICAL','42'),
    ]
    assert all(q.solution and q.solution['text'] for q in questions)
    assert questions[0].options == {'1':'one','2':'two','3':'three','4':'four'}
