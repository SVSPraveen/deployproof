"""Comprehensive test suite covering boundaries, operator logic, and edge cases."""

from billing import calculate_discount


def test_gold_tier_exact_boundary():
    assert calculate_discount(100.0, "gold") == 20.0
    assert calculate_discount(99.99, "gold") == 0.0


def test_silver_tier():
    assert calculate_discount(50.01, "silver") == 5.001
    assert calculate_discount(50.0, "silver") == 0.0


def test_unknown_tier_and_zero():
    assert calculate_discount(200.0, "bronze") == 0.0
    assert calculate_discount(0.0, "gold") == 0.0
