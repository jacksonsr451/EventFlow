from datetime import UTC, datetime

from conftest import (
    COMPENSATION_ID,
    PAYMENT_ID,
    RESERVATION_ID,
    cancelling_order,
    make_order,
    reserved_order,
)


def test_repeated_reservation_result_has_one_business_effect():
    order = make_order()

    for _ in range(2):
        order.accept_reservation(RESERVATION_ID, datetime(2030, 1, 2, tzinfo=UTC))

    assert order.reservation_id == RESERVATION_ID
    assert order.status.name == "STOCK_RESERVED"


def test_repeated_payment_operation_has_one_business_effect():
    order = reserved_order()

    order.start_payment(PAYMENT_ID)
    order.start_payment(PAYMENT_ID)

    assert order.payment_id == PAYMENT_ID
    assert order.status.name == "PAYMENT_PROCESSING"


def test_repeated_release_and_compensation_do_not_finish_twice():
    order = cancelling_order(payment_compensation=True)

    for _ in range(2):
        order.mark_inventory_released(RESERVATION_ID)
        order.mark_payment_compensated(COMPENSATION_ID)
        order.complete_cancellation()

    assert order.status.name == "CANCELLED"


def test_business_identities_are_not_event_ids():
    order = reserved_order()

    order.start_payment(PAYMENT_ID)

    assert order.payment_id == PAYMENT_ID
