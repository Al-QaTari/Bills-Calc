"""Face value must be at least 25,000 and a multiple of 25,000."""

import pytest

from utils import validate_face_value


@pytest.mark.parametrize(
    "value", [25000, 25000.0, 50000, 75000.0, 100000, 1_000_000, 10_000_000]
)
def test_valid_amounts(value):
    assert validate_face_value(value) is None


@pytest.mark.parametrize("value", [0, 1, 10000, 24999.99, -25000])
def test_below_minimum_rejected(value):
    msg = validate_face_value(value)
    assert msg and "25,000" in msg


@pytest.mark.parametrize("value", [30000, 25001, 37500, 60000.5, 99999])
def test_non_multiples_rejected(value):
    msg = validate_face_value(value)
    assert msg and "مضاعفات" in msg


@pytest.mark.parametrize("value", [None, "abc", float("nan")])
def test_garbage_rejected(value):
    assert validate_face_value(value)
