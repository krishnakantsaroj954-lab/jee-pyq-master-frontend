import pytest
from jee_pyq_pipeline.config import _normalise_expected, _normalise_question_type_ranges

def test_normalise_expected_happy_path_ints():
    assert _normalise_expected([1, 2, 3], 'Physics') == ('Physics:1', 'Physics:2', 'Physics:3')

def test_normalise_expected_happy_path_strings():
    assert _normalise_expected(['Maths:1', 'Maths:2'], 'Physics') == ('Maths:1', 'Maths:2')

def test_normalise_expected_happy_path_mixed():
    assert _normalise_expected([1, 'Maths:2', 3], 'Physics') == ('Physics:1', 'Maths:2', 'Physics:3')

def test_normalise_expected_error_not_list():
    with pytest.raises(ValueError, match='expected_question_numbers must be a list'):
        _normalise_expected("not a list", 'Physics')

def test_normalise_expected_error_non_positive_int():
    with pytest.raises(ValueError, match='expected_question_numbers must contain positive integers or subject:number keys'):
        _normalise_expected([0], 'Physics')
    with pytest.raises(ValueError, match='expected_question_numbers must contain positive integers or subject:number keys'):
        _normalise_expected([-1], 'Physics')

def test_normalise_expected_error_invalid_string():
    with pytest.raises(ValueError, match='expected_question_numbers must contain positive integers or subject:number keys'):
        _normalise_expected(['invalid_string'], 'Physics')

def test_normalise_expected_error_invalid_subject_number_key():
    with pytest.raises(ValueError, match='expected_question_numbers contains an invalid subject:number key'):
        _normalise_expected([':1'], 'Physics') # empty subject
    with pytest.raises(ValueError, match='expected_question_numbers contains an invalid subject:number key'):
        _normalise_expected(['Maths:'], 'Physics') # missing number
    with pytest.raises(ValueError, match='expected_question_numbers contains an invalid subject:number key'):
        _normalise_expected(['Maths:abc'], 'Physics') # non-digit number
    with pytest.raises(ValueError, match='expected_question_numbers contains an invalid subject:number key'):
        _normalise_expected(['Maths:-1'], 'Physics') # negative digit
    with pytest.raises(ValueError, match='expected_question_numbers contains an invalid subject:number key'):
        _normalise_expected(['Maths:0'], 'Physics') # zero

def test_normalise_expected_error_duplicate():
    with pytest.raises(ValueError, match='expected_question_numbers must be unique'):
        _normalise_expected([1, 1], 'Physics')
    with pytest.raises(ValueError, match='expected_question_numbers must be unique'):
        _normalise_expected([1, 'Physics:1'], 'Physics')

def test_normalise_question_type_ranges_happy_path_none():
    assert _normalise_question_type_ranges(None) == ()

def test_normalise_question_type_ranges_happy_path_valid():
    raw = [
        {'start': 1, 'end': 10, 'type': 'MCQ'},
        {'start': 11, 'end': 20, 'type': 'NUMERICAL'}
    ]
    assert _normalise_question_type_ranges(raw) == ((1, 10, 'MCQ'), (11, 20, 'NUMERICAL'))

def test_normalise_question_type_ranges_error_not_list():
    with pytest.raises(ValueError, match='question_type_ranges must be a list'):
        _normalise_question_type_ranges("not a list")

def test_normalise_question_type_ranges_error_not_dict():
    with pytest.raises(ValueError, match='question_type_ranges entries must be objects'):
        _normalise_question_type_ranges(["not a dict"])

def test_normalise_question_type_ranges_error_invalid_bounds():
    # start not an int
    with pytest.raises(ValueError, match='question_type_ranges start/end must be positive inclusive integers'):
        _normalise_question_type_ranges([{'start': '1', 'end': 10, 'type': 'MCQ'}])
    # end not an int
    with pytest.raises(ValueError, match='question_type_ranges start/end must be positive inclusive integers'):
        _normalise_question_type_ranges([{'start': 1, 'end': '10', 'type': 'MCQ'}])
    # bool instead of int
    with pytest.raises(ValueError, match='question_type_ranges start/end must be positive inclusive integers'):
        _normalise_question_type_ranges([{'start': True, 'end': 10, 'type': 'MCQ'}])
    # start <= 0
    with pytest.raises(ValueError, match='question_type_ranges start/end must be positive inclusive integers'):
        _normalise_question_type_ranges([{'start': 0, 'end': 10, 'type': 'MCQ'}])
    # start > end
    with pytest.raises(ValueError, match='question_type_ranges start/end must be positive inclusive integers'):
        _normalise_question_type_ranges([{'start': 11, 'end': 10, 'type': 'MCQ'}])

def test_normalise_question_type_ranges_error_invalid_type():
    with pytest.raises(ValueError, match='question_type_ranges type must be MCQ or NUMERICAL'):
        _normalise_question_type_ranges([{'start': 1, 'end': 10, 'type': 'INVALID'}])

def test_normalise_question_type_ranges_error_overlap():
    raw = [
        {'start': 1, 'end': 10, 'type': 'MCQ'},
        {'start': 5, 'end': 15, 'type': 'NUMERICAL'}
    ]
    with pytest.raises(ValueError, match='question_type_ranges must not overlap'):
        _normalise_question_type_ranges(raw)
