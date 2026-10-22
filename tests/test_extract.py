import pytest
from jee_pyq_pipeline.extract import _split_options

def test_split_options_happy_path():
    rows = [
        (1, "What is the capital of France?", [0.0, 0.0, 10.0, 10.0]),
        (1, "(A) Paris", [0.0, 10.0, 10.0, 20.0]),
        (1, "(B) London", [0.0, 20.0, 10.0, 30.0]),
        (1, "(C) Berlin", [0.0, 30.0, 10.0, 40.0]),
        (1, "(D) Madrid", [0.0, 40.0, 10.0, 50.0]),
    ]
    body, options = _split_options(rows)
    assert body == "What is the capital of France?"
    assert options == {"A": "Paris", "B": "London", "C": "Berlin", "D": "Madrid"}

def test_split_options_strange_whitespace():
    rows = [
        (1, "Question text", [0.0, 0.0, 10.0, 10.0]),
        (1, "( A ) Opt 1", [0.0, 10.0, 10.0, 20.0]),
        (1, "( B ) Opt 2", [0.0, 20.0, 10.0, 30.0]),
        (1, "( C ) Opt 3", [0.0, 30.0, 10.0, 40.0]),
        (1, "( D ) Opt 4", [0.0, 40.0, 10.0, 50.0]),
    ]
    body, options = _split_options(rows)
    assert body == "Question text"
    assert options == {"A": "Opt 1", "B": "Opt 2", "C": "Opt 3", "D": "Opt 4"}

def test_split_options_fewer_than_four():
    rows = [
        (1, "Question with 3 options", [0.0, 0.0, 10.0, 10.0]),
        (1, "(A) Option 1", [0.0, 10.0, 10.0, 20.0]),
        (1, "(B) Option 2", [0.0, 20.0, 10.0, 30.0]),
        (1, "(C) Option 3", [0.0, 30.0, 10.0, 40.0]),
    ]
    body, options = _split_options(rows)
    # Should fail closed and return entire text as stem, no options
    assert body == "Question with 3 options (A) Option 1 (B) Option 2 (C) Option 3"
    assert options == {}

def test_split_options_conflicting_labels():
    rows = [
        (1, "Consider these statements:", [0.0, 0.0, 10.0, 10.0]),
        (1, "(A) Statement 1", [0.0, 10.0, 10.0, 20.0]),
        (1, "(B) Statement 2", [0.0, 20.0, 10.0, 30.0]),
        (1, "(C) Statement 3", [0.0, 30.0, 10.0, 40.0]),
        (1, "(D) Statement 4", [0.0, 40.0, 10.0, 50.0]),
        (1, "Which is correct?", [0.0, 50.0, 10.0, 60.0]),
        (1, "(1) A and B", [0.0, 60.0, 10.0, 70.0]),
        (1, "(2) B and C", [0.0, 70.0, 10.0, 80.0]),
        (1, "(3) A and C", [0.0, 80.0, 10.0, 90.0]),
        (1, "(4) All of them", [0.0, 90.0, 10.0, 100.0]),
    ]
    body, options = _split_options(rows)
    assert options == {"1": "A and B", "2": "B and C", "3": "A and C", "4": "All of them"}
    # Verify body includes the statements
    assert "Consider these statements: (A) Statement 1 (B) Statement 2 (C) Statement 3 (D) Statement 4 Which is correct?" in body

def test_split_options_cue_word():
    rows = [
        (1, "Statements:", [0.0, 0.0, 10.0, 10.0]),
        (1, "(1) Stmt 1", [0.0, 10.0, 10.0, 20.0]),
        (1, "(2) Stmt 2", [0.0, 20.0, 10.0, 30.0]),
        (1, "(3) Stmt 3", [0.0, 30.0, 10.0, 40.0]),
        (1, "(4) Stmt 4", [0.0, 40.0, 10.0, 50.0]),
        (1, "Choose the correct option:", [0.0, 50.0, 10.0, 60.0]),
        (1, "(A) 1 and 2", [0.0, 60.0, 10.0, 70.0]),
        (1, "(B) 2 and 3", [0.0, 70.0, 10.0, 80.0]),
        (1, "(C) 3 and 4", [0.0, 80.0, 10.0, 90.0]),
        (1, "(D) 1 and 4", [0.0, 90.0, 10.0, 100.0]),
    ]
    body, options = _split_options(rows)
    assert options == {"A": "1 and 2", "B": "2 and 3", "C": "3 and 4", "D": "1 and 4"}
