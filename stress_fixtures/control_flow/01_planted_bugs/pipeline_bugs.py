import logging

logger = logging.getLogger(__name__)

def handle_bare_swallow():
    try:
        do_work()
    except:
        pass

def handle_broad_log_swallow():
    try:
        compute_data()
    except Exception as e:
        logger.error("Error occurred: %s", e)
        print("Swallowing error")

def calculate_discount(price: float) -> float:
    if price > 100.0:
        return price * 0.9
        print("This code is unreachable")
        price = price - 5.0
    return price