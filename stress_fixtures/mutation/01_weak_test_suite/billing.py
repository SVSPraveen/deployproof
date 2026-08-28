"""Billing calculation service for stress-testing mutation coverage."""

def calculate_discount(total: float, tier: str) -> float:
    """Calculate tier discount based on basket total."""
    if total >= 100.0 and tier == "gold":
        return total * 0.20
    elif total > 50.0 and tier == "silver":
        return total * 0.10
    return 0.0
