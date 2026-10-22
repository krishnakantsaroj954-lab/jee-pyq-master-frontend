import pytest
import hashlib
from pathlib import Path
from jee_pyq_pipeline.util import sha256_file, canonical_json, write_json, safe_normalize

def test_sha256_file(tmp_path: Path):
    test_file = tmp_path / "test.txt"
    content = b"hello world\n"
    test_file.write_bytes(content)

    expected_hash = hashlib.sha256(content).hexdigest()
    assert sha256_file(test_file) == expected_hash

def test_canonical_json():
    # Test sorting of keys and elimination of spaces
    data1 = {"b": 2, "a": 1}
    data2 = {"a": 1, "b": 2}

    expected_bytes = b'{"a":1,"b":2}\n'

    assert canonical_json(data1) == expected_bytes
    assert canonical_json(data2) == expected_bytes

    # Test unicode characters (ensure_ascii=False)
    unicode_data = {"key": "value \u2713"}
    assert canonical_json(unicode_data) == b'{"key":"value \xe2\x9c\x93"}\n'

    # Test arrays and nested objects
    nested_data = {"c": [3, 2, 1], "a": {"z": 26, "y": 25}}
    expected_nested = b'{"a":{"y":25,"z":26},"c":[3,2,1]}\n'
    assert canonical_json(nested_data) == expected_nested

def test_write_json(tmp_path: Path):
    test_file = tmp_path / "output" / "data.json"
    data = {"hello": "world", "number": 42}

    expected_bytes = canonical_json(data)
    expected_hash = hashlib.sha256(expected_bytes).hexdigest()

    # Test that it creates parent directories and returns correct hash
    actual_hash = write_json(test_file, data)

    assert actual_hash == expected_hash
    assert test_file.exists()
    assert test_file.read_bytes() == expected_bytes

def test_safe_normalize():
    # Test multiple spaces/tabs
    assert safe_normalize("hello   world") == "hello world"
    assert safe_normalize("  hello \t world  ") == "hello world"

    # Test single newlines are replaced by spaces
    assert safe_normalize("hello\nworld") == "hello world"

    # Test double newlines are preserved
    assert safe_normalize("hello\n\nworld") == "hello\n\nworld"

    # Test mixed spaces and single newlines
    assert safe_normalize("hello \n world") == "hello world"

    # Test multiple newlines > 2
    assert safe_normalize("hello\n\n\nworld") == "hello\n\n\nworld"
