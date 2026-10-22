from __future__ import annotations
import hashlib, json, re
from pathlib import Path

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')) + '\n').encode()

def write_json(path: Path, value: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json(value))
    return sha256_file(path)

_MULTI_SPACE_RE = re.compile(r'[ \t]+')
_SINGLE_NEWLINE_RE = re.compile(r'(?<!\n)\n(?!\n)')

def safe_normalize(text: str) -> str:
    # Only machine-artifact whitespace normalization; source tokens are retained.
    return _MULTI_SPACE_RE.sub(' ', _SINGLE_NEWLINE_RE.sub(' ', text)).strip()
