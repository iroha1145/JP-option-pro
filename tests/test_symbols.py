from app.domain.symbols import display_code, is_canonical_code, normalize_input_code


def test_four_digit_code_gets_canonical_suffix():
    assert normalize_input_code("7203") == "72030"
    assert normalize_input_code(" 7203 ") == "72030"


def test_five_digit_code_passes_through():
    assert normalize_input_code("72030") == "72030"


def test_letter_codes_are_preserved_not_numeric():
    assert normalize_input_code("285a") == "285A0"
    assert normalize_input_code("285A0") == "285A0"
    assert display_code("285A0") == "285A"


def test_vendor_suffix_tolerated_on_input_only():
    assert normalize_input_code("7203.T") == "72030"


def test_garbage_rejected():
    assert normalize_input_code("") is None
    assert normalize_input_code("TOYOTA") is None
    assert normalize_input_code("12") is None
    assert normalize_input_code(None) is None


def test_display_code_only_strips_trailing_zero_of_five():
    assert display_code("72030") == "7203"
    assert display_code("72035") == "72035"  # 5桁目が意味を持つ銘柄は略さない


def test_is_canonical():
    assert is_canonical_code("72030")
    assert is_canonical_code("285A0")
    assert not is_canonical_code("7203")
