from pathlib import Path
import json
from types import SimpleNamespace
from jee_pyq_pipeline.models import Question
from jee_pyq_pipeline.validate import validate

def cfg(tmp_path, expected=1):
    key=tmp_path/'answers.json'
    key.write_text(json.dumps({'source_document':'paper.pdf','answers':{'1':'A'}}))
    return SimpleNamespace(
        answer_key=key, source_pdf=Path('paper.pdf'), page_range=(1,1),
        expected_question_count=expected,
        expected_question_numbers=tuple(range(1, expected+1)),
        source_has_solutions=False, source_solutions=None
    )

def question(**overrides):
    q=Question(
        'id-1',1,'Question content long enough to validate.',
        {'A':'one','B':'two','C':'three','D':'four'},None,[1],[0,0,1,1],
        {'source_sha256':'a'}
    )
    for k,v in overrides.items():
        setattr(q,k,v)
    return q

def codes(c, questions):
    return {i.code for i in validate(c,questions,1)}

def test_green_record(tmp_path):
    assert not validate(cfg(tmp_path),[question()],1)

def test_missing_answer_file(tmp_path):
    c=cfg(tmp_path); c.answer_key.unlink()
    assert 'INVALID_ANSWER_KEY' in codes(c,[question()])

def test_truncated_question(tmp_path):
    assert 'TRUNCATED_CONTENT' in codes(cfg(tmp_path),[question(text='short')])

def test_missing_required_image(tmp_path):
    assert 'MISSING_REQUIRED_IMAGE' in codes(cfg(tmp_path),[question(requires_figure=True)])

def test_malformed_options(tmp_path):
    assert 'MALFORMED_OPTIONS' in codes(cfg(tmp_path),[question(options={'A':'one'})])

def test_missing_answer(tmp_path):
    c=cfg(tmp_path)
    c.answer_key.write_text(json.dumps({'source_document':'paper.pdf','answers':{}}))
    assert 'MISSING_OR_AMBIGUOUS_ANSWER' in codes(c,[question()])

def test_answer_key_scope_mismatch(tmp_path):
    c=cfg(tmp_path)
    c.answer_key.write_text(json.dumps({'source_document':'paper.pdf','answers':{'2':'A'}}))
    assert 'ANSWER_KEY_SCOPE_MISMATCH' in codes(c,[question()])

def test_duplicate_id(tmp_path):
    assert 'DUPLICATE_ID' in codes(cfg(tmp_path),[question(),question()])

def test_duplicate_source_number(tmp_path):
    assert 'DUPLICATE_SOURCE_NUMBER' in codes(cfg(tmp_path),[question(),question(id='id-2')])

def test_count_mismatch(tmp_path):
    assert 'COUNT_MISMATCH' in codes(cfg(tmp_path,2),[question()],2)

def test_invalid_provenance(tmp_path):
    assert 'INVALID_PROVENANCE' in codes(cfg(tmp_path),[question(pages=[2])])

def test_notation_failure(tmp_path):
    assert 'UNPRESERVED_NOTATION' in codes(cfg(tmp_path),[question(text='A □ preserved?')])

def test_answer_key_source_mismatch(tmp_path):
    c=cfg(tmp_path)
    c.answer_key.write_text(json.dumps({'source_document':'else.pdf','answers':{'1':'A'}}))
    assert 'ANSWER_KEY_SOURCE_MISMATCH' in codes(c,[question()])
