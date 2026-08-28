"""Weak test suite that passes basic smoke tests but leaves critical boundaries untested."""

from billing import calculate_discount


def test_basic_gold_discount():
    # Only tests one arbitrary large value; does not test >= boundary, silver tier, or invalid tiers
    assert calculate_discount(200.0, "gold") == 40.0
