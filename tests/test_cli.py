from pathlib import Path
import json
from types import SimpleNamespace
import pytest
from jee_pyq_pipeline.models import Question
from jee_pyq_pipeline.cli import _check_review_manifest, _question_fingerprint, _paper_identity, _review_template

def cfg(tmp_path, review_manifest_path=None):
    return SimpleNamespace(
        exam='JEE',
        year=2023,
        session='Morning',
        paper='1',
        subject='Physics',
        release='test_release',
        review_manifest=review_manifest_path,
        source_has_solutions=True,
    )

def question(id_val='id-1', **overrides):
    source_hash='a'*64
    q=Question(
        id_val,1,'A particle moves in a straight line with constant velocity.',
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

def test_check_review_manifest_no_manifest_provided(tmp_path):
    config = cfg(tmp_path, review_manifest_path=None)
    q1 = question()
    source_hash = 'a'*64

    ok, status, errors, template = _check_review_manifest(config, [q1], source_hash)

    assert ok is False
    assert status == 'PENDING'
    assert len(errors) == 1
    assert errors[0]['code'] == 'SOURCE_REVIEW_NOT_APPROVED'
    assert errors[0]['message'] == 'No per-question review_manifest was supplied.'

def test_check_review_manifest_missing_file(tmp_path):
    missing_file = tmp_path / 'does_not_exist.json'
    config = cfg(tmp_path, review_manifest_path=missing_file)
    q1 = question()
    source_hash = 'a'*64

    ok, status, errors, template = _check_review_manifest(config, [q1], source_hash)

    assert ok is False
    assert status == 'INVALID'
    assert len(errors) == 1
    assert errors[0]['code'] == 'REVIEW_MANIFEST_MISSING'
    assert errors[0]['message'] == 'Configured review_manifest file does not exist.'

def test_check_review_manifest_invalid_json(tmp_path):
    manifest_file = tmp_path / 'invalid.json'
    manifest_file.write_text('this is not valid json', encoding='utf-8')
    config = cfg(tmp_path, review_manifest_path=manifest_file)
    q1 = question()
    source_hash = 'a'*64

    ok, status, errors, template = _check_review_manifest(config, [q1], source_hash)

    assert ok is False
    assert status == 'INVALID'
    assert len(errors) == 1
    assert errors[0]['code'] == 'REVIEW_MANIFEST_UNREADABLE'
    assert errors[0]['message'].startswith('Could not parse review_manifest:')

def test_check_review_manifest_header_errors(tmp_path):
    manifest_file = tmp_path / 'header_errors.json'
    invalid_manifest = {
        'format': 'wrong/format',
        'source_pdf_sha256': 'wrong_hash',
        'paper_identity': {'exam': 'NEET'} # wrong identity
    }
    manifest_file.write_text(json.dumps(invalid_manifest), encoding='utf-8')
    config = cfg(tmp_path, review_manifest_path=manifest_file)
    q1 = question()
    source_hash = 'a'*64

    ok, status, errors, template = _check_review_manifest(config, [q1], source_hash)

    assert ok is False
    assert status == 'INVALID'
    error_codes = [e['code'] for e in errors]
    assert 'REVIEW_MANIFEST_FORMAT' in error_codes
    assert 'REVIEW_SOURCE_MISMATCH' in error_codes
    assert 'REVIEW_IDENTITY_MISMATCH' in error_codes
    assert 'REVIEW_QUESTIONS_MISSING' in error_codes # Also triggered because 'questions' key is missing

def test_check_review_manifest_entry_structure_errors(tmp_path):
    manifest_file = tmp_path / 'structure_errors.json'
    config = cfg(tmp_path, review_manifest_path=manifest_file)
    source_hash = 'a'*64

    invalid_manifest = {
        'format': 'jee-pyq-source-review/v1',
        'source_pdf_sha256': source_hash,
        'paper_identity': _paper_identity(config),
        'questions': [
            'not_a_dict',
            {'no_id': 'here'},
            {'id': 'id-duplicate'},
            {'id': 'id-duplicate'},
            {'id': 'id-extra'}
        ]
    }
    manifest_file.write_text(json.dumps(invalid_manifest), encoding='utf-8')

    q1 = question(id_val='id-missing')
    ok, status, errors, template = _check_review_manifest(config, [q1], source_hash)

    assert ok is False
    assert status == 'INVALID'
    error_codes = [e['code'] for e in errors]

    assert error_codes.count('REVIEW_ENTRY_INVALID') == 2 # 'not_a_dict' and {'no_id': 'here'}
    assert 'REVIEW_ENTRY_DUPLICATE' in error_codes
    assert 'REVIEW_SCOPE_MISMATCH' in error_codes

def test_check_review_manifest_content_validation_errors(tmp_path):
    manifest_file = tmp_path / 'content_errors.json'
    config = cfg(tmp_path, review_manifest_path=manifest_file)
    source_hash = 'a'*64

    q1 = question(id_val='id-1')

    invalid_manifest = {
        'format': 'jee-pyq-source-review/v1',
        'source_pdf_sha256': source_hash,
        'paper_identity': _paper_identity(config),
        'questions': [
            {
                'id': 'id-1',
                'extracted_sha256': 'wrong_fingerprint',
                'review_status': 'pending', # not verified
                'reviewer': '   ', # missing auditor fields
                'reviewed_at': '',
                'checks': {
                    'question_text': True,
                    # missing subject, source_page, question_type, images, options, answer, solution
                }
            }
        ]
    }
    manifest_file.write_text(json.dumps(invalid_manifest), encoding='utf-8')

    ok, status, errors, template = _check_review_manifest(config, [q1], source_hash)

    assert ok is False
    assert status == 'INVALID'
    error_codes = [e['code'] for e in errors]

    assert 'REVIEW_CONTENT_MISMATCH' in error_codes
    assert 'QUESTION_NOT_REVIEWED' in error_codes
    assert 'REVIEW_AUDIT_FIELDS_MISSING' in error_codes
    assert 'REVIEW_CHECKS_INCOMPLETE' in error_codes

def test_check_review_manifest_happy_path(tmp_path):
    manifest_file = tmp_path / 'happy.json'
    config = cfg(tmp_path, review_manifest_path=manifest_file)
    source_hash = 'a'*64

    q1 = question(id_val='id-1')
    q2 = question(id_val='id-2')
    questions = [q1, q2]

    valid_manifest = _review_template(config, questions, source_hash)
    for entry in valid_manifest['questions']:
        entry['review_status'] = 'verified'
        entry['reviewer'] = 'Test Reviewer'
        entry['reviewed_at'] = '2023-01-01T12:00:00Z'
        for check_key in entry['checks']:
            entry['checks'][check_key] = True

    manifest_file.write_text(json.dumps(valid_manifest), encoding='utf-8')

    ok, status, errors, template = _check_review_manifest(config, questions, source_hash)

    assert ok is True
    assert status == 'APPROVED'
    assert len(errors) == 0
