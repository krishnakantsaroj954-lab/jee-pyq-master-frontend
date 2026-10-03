from __future__ import annotations
import argparse, shutil, signal, sys
from pathlib import Path
from .config import load
from .extract import extract
from .util import sha256_file, write_json
from .validate import validate

VERSION='0.1.0'
def run(config_path: Path, output_root: Path, max_pages: int = 50, timeout_seconds: int = 1200) -> int:
    config=load(config_path)
    if config.page_range[1] - config.page_range[0] + 1 > max_pages: raise ValueError(f'Selected scope exceeds max-pages={max_pages}')
    if not config.source_pdf.is_file(): raise FileNotFoundError(f'Source PDF is missing: {config.source_pdf}')
    if config.source_zip and not config.source_zip.is_file(): raise FileNotFoundError(f'Source ZIP is missing: {config.source_zip}')
    if not config.answer_key.is_file(): raise FileNotFoundError(f'Source answer key is missing: {config.answer_key}')
    if config.source_has_solutions and (not config.source_solutions or not config.source_solutions.is_file()): raise FileNotFoundError('Source solutions were declared but source_solutions is missing')
    source_hash=sha256_file(config.source_pdf); run_id=f'{source_hash[:16]}-{config.page_range[0]}-{config.page_range[1]}'
    out=output_root / run_id
    if out.exists(): shutil.rmtree(out)
    (out/'assets').mkdir(parents=True)
    def timed_out(_signum, _frame): raise TimeoutError(f'Extraction exceeded {timeout_seconds} seconds')
    prior = signal.signal(signal.SIGALRM, timed_out)
    signal.alarm(timeout_seconds)
    try: questions, assets, extraction_issues, page_count=extract(config,out/'assets')
    finally:
        signal.alarm(0); signal.signal(signal.SIGALRM, prior)
    issues=extraction_issues + validate(config,questions,page_count)
    # The batch is invalid if any blocking issue. No import client or credentials exist in this project.
    status='VALIDATED' if not any(i.blocking for i in issues) else 'QUARANTINED'
    for q in questions:
        if status != 'VALIDATED': q.status='QUARANTINED'
    records={'validated':[q.json() for q in questions if q.status=='VALIDATED'], 'quarantined':[q.json() for q in questions if q.status=='QUARANTINED'], 'rejected':[]}
    checksums={name:write_json(out/f'{name}.json',values) for name,values in records.items()}
    intake={'release':config.release,'source_pdf':config.source_pdf.name,'source_pdf_sha256':source_hash,'source_zip': None if not config.source_zip else {'filename':config.source_zip.name,'sha256':sha256_file(config.source_zip)},'pdf_page_count':page_count,'selected_page_range':list(config.page_range),'identity':{'exam':config.exam,'year':config.year,'session':config.session,'paper':config.paper,'subject':config.subject}}
    write_json(out/'source-intake.json',intake)
    report={'validator_version':VERSION,'status':status,'counts':{k:len(v) for k,v in records.items()},'blocking_issue_count':len([i for i in issues if i.blocking]),'issues':[i.__dict__ for i in issues]}
    write_json(out/'validation-report.json',report)
    manifest={'format':'jee-pyq-review-batch/v1','run_id':run_id,'created_at':'DETERMINISTIC_FROM_SOURCE_HASH','status':status,'source_intake':'source-intake.json','records':checksums,'asset_count':len(assets),'validator_version':VERSION,'import_boundary':'IMPORT_READY.json is emitted only for an entirely VALIDATED batch; this pipeline never imports.'}
    write_json(out/'batch-manifest.json',manifest)
    if status=='VALIDATED': write_json(out/'IMPORT_READY.json',{'run_id':run_id,'manifest_sha256':sha256_file(out/'batch-manifest.json'),'status':'VALIDATED','instruction':'External authorized importer must verify this marker and manifest checksums before any atomic import.'})
    print(out)
    return 0 if status=='VALIDATED' else 2

def main(argv=None):
    p=argparse.ArgumentParser(description='Fail-closed representative JEE PYQ PDF pipeline (no D1 import)')
    p.add_argument('--config',required=True,type=Path); p.add_argument('--output',default=Path('pipeline-output'),type=Path)
    p.add_argument('--max-pages', type=int, default=50); p.add_argument('--timeout-seconds', type=int, default=1200)
    args=p.parse_args(argv)
    try:
        if args.max_pages < 1 or args.timeout_seconds < 1: raise ValueError("max-pages and timeout-seconds must be positive")
        return run(args.config,args.output,args.max_pages,args.timeout_seconds)
    except Exception as e:
        print(f'EARLY FAIL: {e}',file=sys.stderr); return 2
if __name__=='__main__': raise SystemExit(main())
