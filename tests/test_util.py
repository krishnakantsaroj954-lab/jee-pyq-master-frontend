from pathlib import Path
from jee_pyq_pipeline.util import sha256_file, canonical_json, write_json, safe_normalize

def test_sha256_file(tmp_path):
    p = tmp_path / "test.txt"
    p.write_bytes(b"hello world")
    assert sha256_file(p) == "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"

def test_canonical_json():
    obj = {"c": 3, "a": 1, "b": 2}
    expected = b'{"a":1,"b":2,"c":3}\n'
    assert canonical_json(obj) == expected

def test_write_json(tmp_path):
    p = tmp_path / "data" / "output.json"
    obj = {"key": "value"}
    h = write_json(p, obj)
    assert p.exists()
    assert p.read_bytes() == b'{"key":"value"}\n'
    assert h == "cbdea9ab8317fcd1e3b3a8626c735b7dfb3a929eb927b02aeab7e7f67a511d8a"

def test_safe_normalize():
    assert safe_normalize("  hello   world  ") == "hello world"
    assert safe_normalize("line1\nline2") == "line1 line2"
    assert safe_normalize("line1\n\nline2") == "line1\n\nline2"
