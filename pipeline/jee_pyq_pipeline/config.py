from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path

REQUIRED = {'source_pdf', 'release', 'exam', 'year', 'session', 'paper', 'subject', 'page_range', 'expected_question_count', 'expected_question_numbers', 'answer_key', 'source_has_solutions'}
@dataclass(frozen=True)
class PaperConfig:
    source_pdf: Path; release: str; exam: str; year: int; session: str; paper: str; subject: str
    page_range: tuple[int, int]; expected_question_count: int; expected_question_numbers: tuple[int, ...]; answer_key: Path; source_has_solutions: bool; source_solutions: Path | None = None; source_zip: Path | None = None

def load(path: Path) -> PaperConfig:
    raw = json.loads(path.read_text(encoding='utf-8'))
    missing = REQUIRED - raw.keys()
    if missing: raise ValueError(f'Configuration missing required fields: {sorted(missing)}')
    base = path.parent
    pages = raw['page_range']
    if not (isinstance(pages, list) and len(pages) == 2 and all(isinstance(x, int) and x > 0 for x in pages) and pages[0] <= pages[1]):
        raise ValueError('page_range must be [positive_start, positive_end]')
    if not isinstance(raw['expected_question_count'], int) or raw['expected_question_count'] <= 0: raise ValueError('expected_question_count must be positive')
    nums=raw['expected_question_numbers']
    if not isinstance(nums, list) or len(nums) != raw['expected_question_count'] or any(not isinstance(n, int) or n <= 0 for n in nums) or len(set(nums)) != len(nums): raise ValueError('expected_question_numbers must be unique positive integers matching expected_question_count')
    if not isinstance(raw['source_has_solutions'], bool): raise ValueError('source_has_solutions must be boolean')
    if raw['source_has_solutions'] and not raw.get('source_solutions'): raise ValueError('source_solutions is required when source_has_solutions is true')
    identity = ('release','exam','session','paper','subject')
    if any(not isinstance(raw[k], str) or not raw[k].strip() or raw[k].strip().lower() in {'unknown','ambiguous','tbd'} for k in identity):
        raise ValueError('Ambiguous source identity metadata is not accepted')
    resolve = lambda p: (base / p).resolve() if not Path(p).is_absolute() else Path(p)
    return PaperConfig(resolve(raw['source_pdf']), raw['release'], raw['exam'], raw['year'], raw['session'], raw['paper'], raw['subject'], tuple(pages), raw['expected_question_count'], tuple(nums), resolve(raw['answer_key']), raw['source_has_solutions'], resolve(raw['source_solutions']) if raw.get('source_solutions') else None, resolve(raw['source_zip']) if raw.get('source_zip') else None)
