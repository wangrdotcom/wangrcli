from wangr.utils import safe_division, safe_float


def test_safe_division():
    assert safe_division(10, 2) == 5
    assert safe_division(10, 0) == 0.0


def test_safe_float():
    assert safe_float("1.25") == 1.25
    assert safe_float(None, default=3.0) == 3.0
