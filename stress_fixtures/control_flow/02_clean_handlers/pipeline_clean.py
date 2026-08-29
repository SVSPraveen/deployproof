import logging

logger = logging.getLogger(__name__)

def handle_cleanup():
    try:
        acquire_lock()
    except:
        release_lock()
        raise

def handle_logging_propagate():
    try:
        compute_data()
    except Exception as e:
        logger.error("Error occurred: %s", e)
        raise

def handle_with_error_dict():
    try:
        val = int("123")
        return {"status": "ok", "value": val}
    except Exception as e:
        logger.warning("Parse failed: %s", e)
        return {"status": "error", "error": str(e)}

def calculate_discount(price: float) -> float:
    if price > 100.0:
        return price * 0.9
    return price