from __future__ import annotations
import argparse,json,shutil,signal,sys
from pathlib import Path
from .config import load
from .extract import extract
from .util import sha256_file,write_json
from .validate import validate

VERSION='0.3.0'

def _build_batch(config,output_dir:Path,timeout_seconds:int):
    (output_dir/'assets').mkdir(parents=True,exist_ok=True)
    source_hash=sha256_file(config.source_pdf)

    def timed_out(_signum,_frame):
        raise TimeoutError(f'Extraction exceeded {timeout_seconds} seconds')

    prior=signal.signal(signal.SIGALRM,timed_out)
    signal.alarm(timeout_seconds)
    try:
        questions,assets,extraction_issues,page_count=extract(config,output_dir/'assets')
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM,prior)

    issues=extraction_issues+validate(config,questions,page_count)
    status='VALIDATED' if not any(i.blocking for i in issues) else 'QUARANTINED'
    for q in questions:
        if status!='VALIDATED' and q.status!='Dropped':
            q.status='QUARANTINED'

    # Dropped questions remain in the validated paper payload with status="Dropped";
    # they are never silently omitted from the 75-question paper.
    records={
        'validated':[q.json() for q in questions if q.status in ('VALIDATED','Dropped')],
        'quarantined':[q.json() for q in questions if q.status=='QUARANTINED'],
        'rejected':[],
        'dropped':[q.json() for q in questions if q.status=='Dropped'],
    }
    checksums={name:write_json(output_dir/f'{name}.json',values) for name,values in records.items()}

    answer_evidence={
        'source_document':config.source_pdf.name,
        'source_sha256':source_hash,
        'answers':{f'{q.subject}:{q.source_question_number}':q.answer for q in questions if q.answer is not None and q.status!='Dropped'},
        'question_types':{f'{q.subject}:{q.source_question_number}':q.question_type for q in questions},
    }
    solution_evidence={
        'source_document':config.source_pdf.name,
        'source_sha256':source_hash,
        'solutions':{f'{q.subject}:{q.source_question_number}':q.solution for q in questions if q.solution},
    }
    checksums['source_answers']=write_json(output_dir/'source-answers.json',answer_evidence)
    checksums['source_solutions']=write_json(output_dir/'source-solutions.json',solution_evidence)

    intake={
        'release':config.release,
        'source_pdf':config.source_pdf.name,
        'source_pdf_sha256':source_hash,
        'source_zip':None if not config.source_zip else {'filename':config.source_zip.name,'sha256':sha256_file(config.source_zip)},
        'pdf_page_count':page_count,
        'selected_page_range':list(config.page_range),
        'identity':{'exam':config.exam,'year':config.year,'session':config.session,'paper':config.paper,'subject':config.subject},
    }
    write_json(output_dir/'source-intake.json',intake)

    report={
        'validator_version':VERSION,
        'status':status,
        'counts':{k:len(v) for k,v in records.items()},
        'status_counts':{
            'VALIDATED':sum(1 for q in questions if q.status=='VALIDATED'),
            'Dropped':sum(1 for q in questions if q.status=='Dropped'),
            'QUARANTINED':sum(1 for q in questions if q.status=='QUARANTINED'),
        },
        'question_type_counts':{
            'MCQ':sum(1 for q in questions if q.question_type=='MCQ'),
            'NUMERICAL':sum(1 for q in questions if q.question_type=='NUMERICAL'),
            'UNKNOWN':sum(1 for q in questions if q.question_type=='UNKNOWN'),
        },
        'subject_counts':{
            s:sum(1 for q in questions if q.subject==s) for s in ('Physics','Chemistry','Mathematics')
        },
        'blocking_issue_count':sum(i.blocking for i in issues),
        'issues':[i.__dict__ for i in issues],
    }
    write_json(output_dir/'validation-report.json',report)

    manifest={
        'format':'jee-pyq-review-batch/v2',
        'run_id':output_dir.name,
        'created_at':'DETERMINISTIC_FROM_SOURCE_HASH',
        'status':status,
        'source_intake':'source-intake.json',
        'records':checksums,
        'asset_count':len(assets),
        'validator_version':VERSION,
        'import_boundary':'IMPORT_READY.json is emitted only for an entirely VALIDATED batch; this pipeline never imports and never touches D1.',
    }
    write_json(output_dir/'batch-manifest.json',manifest)

    if status=='VALIDATED':
        write_json(output_dir/'IMPORT_READY.json',{
            'run_id':output_dir.name,
            'manifest_sha256':sha256_file(output_dir/'batch-manifest.json'),
            'validated_json_sha256':checksums['validated'],
            'source_answers_sha256':checksums['source_answers'],
            'source_solutions_sha256':checksums['source_solutions'],
            'dropped_json_sha256':checksums['dropped'],
            'status':'VALIDATED',
            'instruction':'Import must consume this exact batch directory/artifact and reverify all checksums; do not re-extract the source PDF.',
        })
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
    if out.exists() and not force_reextract:
        if ready.is_file() and (out/'batch-manifest.json').is_file():
            marker=json.loads(ready.read_text(encoding='utf-8'))
            manifest_sha=sha256_file(out/'batch-manifest.json')
            if marker.get('status')=='VALIDATED' and marker.get('run_id')==run_id and marker.get('manifest_sha256')==manifest_sha:
                print(out)
                return 0
        raise FileExistsError(f'Batch already exists at {out}; refusing to delete/re-extract. Use --force-reextract only for an intentional new extraction.')

    tmp=output_root/f'.{run_id}.partial'
    if tmp.exists():
        shutil.rmtree(tmp)
    if out.exists():
        shutil.rmtree(out)
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
