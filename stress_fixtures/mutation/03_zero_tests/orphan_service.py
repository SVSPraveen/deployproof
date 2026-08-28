"""Payment processor module with zero matching unit tests."""

def process_payment(amount: float, card_valid: bool) -> bool:
    """Process customer charge if amount is positive and card is valid."""
    if amount > 0 and card_valid:
        return True
    return False
