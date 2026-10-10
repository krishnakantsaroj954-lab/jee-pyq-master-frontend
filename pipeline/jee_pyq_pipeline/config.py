from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path

REQUIRED = {
    'source_pdf', 'release', 'exam', 'year', 'session', 'paper',
    'subject', 'page_range', 'expected_question_count',
    'expected_question_numbers', 'source_has_solutions'
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
    source_has_solutions: bool
    source_zip: Path | None = None
    answer_key: Path | None = None
    source_solutions: Path | None = None
    review_manifest: Path | None = None
    # Optional paper-specific, source-grounded type bands over printed question numbers.
    question_type_ranges: tuple[tuple[int, int, str], ...] = ()

def _normalise_expected(raw, subject: str) -> tuple[str, ...]:
    if not isinstance(raw, list):
        raise ValueError('expected_question_numbers must be a list')
    values=[]
    for item in raw:
        if isinstance(item, int) and item > 0:
            values.append(f'{subject}:{item}')
        elif isinstance(item, str) and ':' in item:
            s,n=item.split(':',1)
            if s.strip() and n.isdigit() and int(n) > 0:
                values.append(f'{s.strip()}:{int(n)}')
            else:
                raise ValueError('expected_question_numbers contains an invalid subject:number key')
        else:
            raise ValueError('expected_question_numbers must contain positive integers or subject:number keys')
    if len(values) != len(set(values)):
        raise ValueError('expected_question_numbers must be unique')
    return tuple(values)

def _normalise_question_type_ranges(raw) -> tuple[tuple[int, int, str], ...]:
    """Validate explicit source-section type bands; no implicit numbering assumptions."""
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError('question_type_ranges must be a list')
    ranges=[]
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError('question_type_ranges entries must be objects')
        start, end, kind = item.get('start'), item.get('end'), item.get('type')
        if not (isinstance(start, int) and not isinstance(start, bool)
                and isinstance(end, int) and not isinstance(end, bool)
                and 1 <= start <= end):
            raise ValueError('question_type_ranges start/end must be positive inclusive integers')
        if kind not in {'MCQ', 'NUMERICAL'}:
            raise ValueError('question_type_ranges type must be MCQ or NUMERICAL')
        if any(not (end < prior_start or start > prior_end) for prior_start, prior_end, _ in ranges):
            raise ValueError('question_type_ranges must not overlap')
        ranges.append((start, end, kind))
    return tuple(ranges)

def load(path: Path) -> PaperConfig:
    raw=json.loads(path.read_text(encoding='utf-8'))
    missing=REQUIRED-raw.keys()
    if missing:
        raise ValueError(f'Configuration missing required fields: {sorted(missing)}')
    pages=raw['page_range']
    if not (isinstance(pages,list) and len(pages)==2 and all(isinstance(x,int) and x>0 for x in pages) and pages[0]<=pages[1]):
        raise ValueError('page_range must be [positive_start, positive_end]')
    count=raw['expected_question_count']
    if not isinstance(count,int) or count<=0:
        raise ValueError('expected_question_count must be positive')
    subject=raw['subject']
    if not isinstance(subject,str) or not subject.strip():
        raise ValueError('subject must be non-empty')
    numbers=_normalise_expected(raw['expected_question_numbers'], subject.strip())
    if len(numbers)!=count:
        raise ValueError('expected_question_numbers length must match expected_question_count')
    type_ranges=_normalise_question_type_ranges(raw.get('question_type_ranges'))
    if type_ranges:
        printed_numbers=[int(item.rsplit(':',1)[1]) for item in numbers]
        if len(printed_numbers) != len(set(printed_numbers)):
            raise ValueError('question_type_ranges requires unique paper-wide printed question numbers')
        expected_printed=set(printed_numbers)
        if any(any(number not in expected_printed for number in range(start,end+1))
               for start,end,_kind in type_ranges):
            raise ValueError('question_type_ranges may only cover configured question numbers')
    if not isinstance(raw['source_has_solutions'],bool):
        raise ValueError('source_has_solutions must be boolean')
    identity=('release','exam','session','paper','subject')
    if any(not isinstance(raw[k],str) or not raw[k].strip() or raw[k].strip().lower() in {'unknown','ambiguous','tbd'} for k in identity):
        raise ValueError('Ambiguous source identity metadata is not accepted')
    base=path.parent
    resolve=lambda p: (base/Path(p)).resolve() if not Path(p).is_absolute() else Path(p)
    return PaperConfig(
        resolve(raw['source_pdf']), raw['release'], raw['exam'], raw['year'],
        raw['session'], raw['paper'], subject.strip(), tuple(pages), count, numbers,
        raw['source_has_solutions'],
        resolve(raw['source_zip']) if raw.get('source_zip') else None,
        resolve(raw['answer_key']) if raw.get('answer_key') else None,
        resolve(raw['source_solutions']) if raw.get('source_solutions') else None,
        resolve(raw['review_manifest']) if raw.get('review_manifest') else None,
        type_ranges,
    )
