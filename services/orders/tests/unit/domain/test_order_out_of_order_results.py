from datetime import UTC, datetime

import testrunner
from conftest import PAYMENT_ID, RESERVATION_ID, make_order, payment_processing_order


def domain_error():
    from eventflow_orders.domain.exceptions import DomainError

    return DomainError


def test_payment_approved_before_reservation_is_not_accepted():
    order = make_order()

    with testrunner.raises(domain_error()):
        order.approve_payment(PAYMENT_ID)

    assert order.status.name == "PENDING"


def test_inventory_result_after_cancelled_is_not_resurrection():
    order = make_order()
    order.reject_reservation(reason="unavailable")

    with testrunner.raises(domain_error()):
        order.accept_reservation(RESERVATION_ID, datetime(2030, 1, 2, tzinfo=UTC))

    assert order.status.name == "CANCELLED"


def test_payment_decline_after_confirmed_is_not_a_regression():
    order = payment_processing_order()
    order.approve_payment(PAYMENT_ID)
    order.confirm(at=datetime(2029, 12, 31, tzinfo=UTC))

    with testrunner.raises(domain_error()):
        order.decline_payment()

    assert order.status.name == "CONFIRMED"


def test_release_before_cancellation_does_not_cancel_order():
    order = payment_processing_order()

    with testrunner.raises(domain_error()):
        order.mark_inventory_released(RESERVATION_ID)

    assert order.status.name == "PAYMENT_PROCESSING"


def test_unexpected_payment_compensation_does_not_change_order():
    order = payment_processing_order()
    compensation_id = __import__("uuid").UUID("70000000-0000-4000-8000-000000000001")

    with testrunner.raises(domain_error()):
        order.mark_payment_compensated(compensation_id)

    assert order.status.name == "PAYMENT_PROCESSING"
