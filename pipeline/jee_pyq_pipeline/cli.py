from __future__ import annotations
import argparse,hashlib,json,shutil,signal,sys
from pathlib import Path
from .config import load
from .extract import extract
from .util import sha256_file,write_json
from .validate import validate

VERSION='0.4.0'


def _paper_identity(config):
    return {
        'exam': config.exam, 'year': config.year, 'session': config.session,
        'paper': config.paper, 'subject': config.subject, 'release': config.release,
    }


def _question_fingerprint(question):
    payload = question.json()
    # Review approval is tied to all extracted material, not transient workflow state.
    payload.pop('status', None)
    payload.pop('issues', None)
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(body.encode('utf-8')).hexdigest()


def _required_review_checks(question, source_has_solutions):
    if question.status == 'Dropped':
        return ['question_text', 'subject', 'source_page', 'dropped_status', 'images']
    checks = ['question_text', 'subject', 'source_page', 'question_type', 'images']
    if question.question_type == 'MCQ':
        checks.extend(['options', 'answer'])
    elif question.question_type == 'NUMERICAL':
        checks.append('answer')
    if source_has_solutions:
        checks.append('solution')
    return checks


def _review_template(config, questions, source_hash):
    return {
        'format': 'jee-pyq-source-review/v1',
        'source_pdf_sha256': source_hash,
        'paper_identity': _paper_identity(config),
        'instructions': (
            'Compare each question, all options, answer, solution, subject, source page, '
            'and image association against the original source. Set review_status to '
            'verified only after the listed checks are all true. Do not infer missing content.'
        ),
        'questions': [
            {
                'id': q.id,
                'extracted_sha256': _question_fingerprint(q),
                'review_status': 'pending',
                'reviewer': '',
                'reviewed_at': '',
                'checks': {name: False for name in _required_review_checks(q, config.source_has_solutions)},
            }
            for q in questions
        ],
    }


def _check_review_manifest(config, questions, source_hash):
    template = _review_template(config, questions, source_hash)
    if not config.review_manifest:
        return False, 'PENDING', [
            {'code': 'SOURCE_REVIEW_NOT_APPROVED', 'message': 'No per-question review_manifest was supplied.'}
        ], template
    if not config.review_manifest.is_file():
        return False, 'INVALID', [
            {'code': 'REVIEW_MANIFEST_MISSING', 'message': 'Configured review_manifest file does not exist.'}
        ], template
    try:
        manifest = json.loads(config.review_manifest.read_text(encoding='utf-8'))
    except Exception as error:
        return False, 'INVALID', [
            {'code': 'REVIEW_MANIFEST_UNREADABLE', 'message': f'Could not parse review_manifest: {error}'}
        ], template

    errors = []
    if manifest.get('format') != 'jee-pyq-source-review/v1':
        errors.append({'code': 'REVIEW_MANIFEST_FORMAT', 'message': 'Unsupported review manifest format.'})
    if manifest.get('source_pdf_sha256') != source_hash:
        errors.append({'code': 'REVIEW_SOURCE_MISMATCH', 'message': 'Review manifest source SHA-256 does not match this PDF.'})
    if manifest.get('paper_identity') != _paper_identity(config):
        errors.append({'code': 'REVIEW_IDENTITY_MISMATCH', 'message': 'Review manifest paper identity does not match this run.'})

    entries = manifest.get('questions')
    if not isinstance(entries, list):
        entries = []
        errors.append({'code': 'REVIEW_QUESTIONS_MISSING', 'message': 'Review manifest questions must be a list.'})
    indexed = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get('id'), str):
            errors.append({'code': 'REVIEW_ENTRY_INVALID', 'message': 'Review manifest contains an entry without a question id.'})
            continue
        qid = entry['id']
        if qid in indexed:
            errors.append({'code': 'REVIEW_ENTRY_DUPLICATE', 'message': f'Duplicate review entry for {qid}.'})
        indexed[qid] = entry
    expected_ids = {q.id for q in questions}
    if set(indexed) != expected_ids:
        errors.append({
            'code': 'REVIEW_SCOPE_MISMATCH',
            'message': f'Review entries must cover every extracted question exactly once; missing={sorted(expected_ids-set(indexed))[:8]}, extra={sorted(set(indexed)-expected_ids)[:8]}.',
        })

    for question in questions:
        entry = indexed.get(question.id)
        if not entry:
            continue
        if entry.get('extracted_sha256') != _question_fingerprint(question):
            errors.append({'code': 'REVIEW_CONTENT_MISMATCH', 'message': f'Extraction changed after review for {question.id}.'})
        if entry.get('review_status') != 'verified':
            errors.append({'code': 'QUESTION_NOT_REVIEWED', 'message': f'{question.id} is not marked verified.'})
        if not str(entry.get('reviewer', '')).strip() or not str(entry.get('reviewed_at', '')).strip():
            errors.append({'code': 'REVIEW_AUDIT_FIELDS_MISSING', 'message': f'{question.id} must record reviewer and reviewed_at.'})
        checks = entry.get('checks') if isinstance(entry.get('checks'), dict) else {}
        missing_checks = [name for name in _required_review_checks(question, config.source_has_solutions) if checks.get(name) is not True]
        if missing_checks:
            errors.append({
                'code': 'REVIEW_CHECKS_INCOMPLETE',
                'message': f'{question.id} review checks are not complete: {", ".join(missing_checks)}.',
            })
    return not errors, ('APPROVED' if not errors else 'INVALID'), errors, template

def _run_extraction(config, output_dir: Path, timeout_seconds: int):
    (output_dir / 'assets').mkdir(parents=True, exist_ok=True)

    def timed_out(_signum, _frame):
        raise TimeoutError(f'Extraction exceeded {timeout_seconds} seconds')

    prior = signal.signal(signal.SIGALRM, timed_out)
    signal.alarm(timeout_seconds)
    try:
        return extract(config, output_dir / 'assets')
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, prior)


def _validate_batch(config, questions, extraction_issues, page_count, source_hash):
    issues = extraction_issues + validate(config, questions, page_count)
    structural_blockers = sum(1 for issue in issues if issue.blocking)
    review_ok, review_status, review_issues, review_template = _check_review_manifest(config, questions, source_hash)

    if structural_blockers:
        status = 'QUARANTINED'
    elif review_ok:
        status = 'VALIDATED'
    else:
        status = 'REVIEW_REQUIRED'

    for q in questions:
        if q.status == 'Dropped':
            continue
        if structural_blockers:
            q.status = 'QUARANTINED'
        elif status == 'REVIEW_REQUIRED':
            q.status = 'REVIEW_REQUIRED'
        else:
            q.status = 'VALIDATED'

    return status, issues, review_status, review_issues, review_template


def _serialize_batch(config, output_dir: Path, source_hash: str, status: str, questions, assets, issues, page_count, review_status, review_issues, review_template):
    # A structurally clean parse is not source-verified until every record has
    # explicit, content-bound human review. Dropped questions remain in the paper.
    records = {
        'validated': [q.json() for q in questions if status == 'VALIDATED' and q.status in ('VALIDATED', 'Dropped')],
        'review_required': [q.json() for q in questions if status == 'REVIEW_REQUIRED' and q.status in ('REVIEW_REQUIRED', 'Dropped')],
        'quarantined': [q.json() for q in questions if q.status == 'QUARANTINED'],
        'rejected': [],
        'dropped': [q.json() for q in questions if q.status == 'Dropped'],
    }

    review_template_checksum = write_json(output_dir / 'review-manifest-template.json', review_template)
    checksums = {name: write_json(output_dir / f'{name}.json', values) for name, values in records.items()}

    answer_evidence = {
        'source_document': config.source_pdf.name,
        'source_sha256': source_hash,
        'answers': {f'{q.subject}:{q.source_question_number}': q.answer for q in questions if q.answer is not None and q.status != 'Dropped'},
        'question_types': {f'{q.subject}:{q.source_question_number}': q.question_type for q in questions},
    }
    solution_evidence = {
        'source_document': config.source_pdf.name,
        'source_sha256': source_hash,
        'solutions': {f'{q.subject}:{q.source_question_number}': q.solution for q in questions if q.solution},
    }
    checksums['source_answers'] = write_json(output_dir / 'source-answers.json', answer_evidence)
    checksums['source_solutions'] = write_json(output_dir / 'source-solutions.json', solution_evidence)
    checksums['review_template'] = review_template_checksum

    intake = {
        'release': config.release,
        'source_pdf': config.source_pdf.name,
        'source_pdf_sha256': source_hash,
        'source_zip': None if not config.source_zip else {'filename': config.source_zip.name, 'sha256': sha256_file(config.source_zip)},
        'pdf_page_count': page_count,
        'selected_page_range': list(config.page_range),
        'identity': {'exam': config.exam, 'year': config.year, 'session': config.session, 'paper': config.paper, 'subject': config.subject},
    }
    write_json(output_dir / 'source-intake.json', intake)

    report = {
        'validator_version': VERSION,
        'status': status,
        'counts': {k: len(v) for k, v in records.items()},
        'status_counts': {
            'VALIDATED': sum(1 for q in questions if q.status == 'VALIDATED'),
            'REVIEW_REQUIRED': sum(1 for q in questions if q.status == 'REVIEW_REQUIRED'),
            'Dropped': sum(1 for q in questions if q.status == 'Dropped'),
            'QUARANTINED': sum(1 for q in questions if q.status == 'QUARANTINED'),
        },
        'review_gate': {
            'status': review_status,
            'manifest': str(config.review_manifest) if config.review_manifest else None,
            'issues': review_issues,
            'template': 'review-manifest-template.json',
        },
        'question_type_counts': {
            'MCQ': sum(1 for q in questions if q.question_type == 'MCQ'),
            'NUMERICAL': sum(1 for q in questions if q.question_type == 'NUMERICAL'),
            'UNKNOWN': sum(1 for q in questions if q.question_type == 'UNKNOWN'),
        },
        'subject_counts': {
            s: sum(1 for q in questions if q.subject == s) for s in ('Physics', 'Chemistry', 'Mathematics')
        },
        'blocking_issue_count': sum(i.blocking for i in issues) + len(review_issues),
        'issues': [i.__dict__ for i in issues] + [
            {'code': item['code'], 'message': item['message'], 'blocking': True, 'question_id': None}
            for item in review_issues
        ],
    }
    write_json(output_dir / 'validation-report.json', report)

    manifest = {
        'format': 'jee-pyq-review-batch/v2',
        'run_id': output_dir.name,
        'created_at': 'DETERMINISTIC_FROM_SOURCE_HASH',
        'status': status,
        'source_intake': 'source-intake.json',
        'records': checksums,
        'asset_count': len(assets),
        'validator_version': VERSION,
        'import_boundary': 'IMPORT_READY.json is emitted only after structural checks pass and a complete content-bound per-question source review is approved; this pipeline never imports and never touches D1.',
    }
    write_json(output_dir / 'batch-manifest.json', manifest)

    if status == 'VALIDATED':
        write_json(output_dir / 'IMPORT_READY.json', {
            'run_id': output_dir.name,
            'manifest_sha256': sha256_file(output_dir / 'batch-manifest.json'),
            'validated_json_sha256': checksums['validated'],
            'source_answers_sha256': checksums['source_answers'],
            'source_solutions_sha256': checksums['source_solutions'],
            'dropped_json_sha256': checksums['dropped'],
            'status': 'VALIDATED',
            'instruction': 'Import must consume this exact batch directory/artifact and reverify all checksums; do not re-extract the source PDF.',
        })


def _build_batch(config, output_dir: Path, timeout_seconds: int):
    source_hash = sha256_file(config.source_pdf)
    questions, assets, extraction_issues, page_count = _run_extraction(config, output_dir, timeout_seconds)

    status, issues, review_status, review_issues, review_template = _validate_batch(
        config, questions, extraction_issues, page_count, source_hash
    )

    _serialize_batch(
        config, output_dir, source_hash, status, questions, assets, issues,
        page_count, review_status, review_issues, review_template
    )

    return status

def run(config_path:Path,output_root:Path,max_pages:int=50,timeout_seconds:int=1200,force_reextract:bool=False)->int:
    config=load(config_path)
    selected_pages=config.page_range[1]-config.page_range[0]+1
    if selected_pages>max_pages:
        raise ValueError(f'Selected scope exceeds max-pages={max_pages}')
    if not config.source_pdf.is_file():
        raise FileNotFoundError(f'Source PDF is missing: {config.source_pdf}')
    if config.source_zip and not config.source_zip.is_file():
        raise FileNotFoundError(f'Source ZIP is missing: {config.source_zip}')

    source_hash=sha256_file(config.source_pdf)
    run_id=f'{source_hash[:16]}-{config.page_range[0]}-{config.page_range[1]}'
    out=output_root/run_id
    ready=out/'IMPORT_READY.json'
    if out.exists():
        if ready.is_file() and (out/'batch-manifest.json').is_file():
            marker=json.loads(ready.read_text(encoding='utf-8'))
            manifest_sha=sha256_file(out/'batch-manifest.json')
            if marker.get('status')=='VALIDATED' and marker.get('run_id')==run_id and marker.get('manifest_sha256')==manifest_sha:
                print(out)
                return 0
        raise FileExistsError(
            f'Batch already exists at {out}; refusing to delete review evidence even when --force-reextract is supplied. '
            'Use a new output root or archive the old batch manually.'
        )

    tmp=output_root/f'.{run_id}.partial'
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    try:
        status=_build_batch(config,tmp,timeout_seconds)
        tmp.replace(out)
    except Exception:
        shutil.rmtree(tmp,ignore_errors=True)
        raise
    print(out)
    return 0 if status=='VALIDATED' else 2

def main(argv=None):
    p=argparse.ArgumentParser(description='Fail-closed representative JEE PYQ PDF pipeline (no D1 import)')
    p.add_argument('--config',required=True,type=Path)
    p.add_argument('--output',default=Path('pipeline-output'),type=Path)
    p.add_argument('--max-pages',type=int,default=50)
    p.add_argument('--timeout-seconds',type=int,default=1200)
    p.add_argument('--force-reextract',action='store_true')
    args=p.parse_args(argv)
    try:
        if args.max_pages<1 or args.timeout_seconds<1:
            raise ValueError('max-pages and timeout-seconds must be positive')
        return run(args.config,args.output,args.max_pages,args.timeout_seconds,args.force_reextract)
    except Exception as e:
        print(f'EARLY FAIL: {e}',file=sys.stderr)
        return 2

if __name__=='__main__':
    raise SystemExit(main())
