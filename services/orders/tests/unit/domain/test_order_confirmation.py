from datetime import UTC, datetime

import testrunner
from conftest import PAYMENT_ID, RESERVATION_ID, make_order, payment_processing_order


def status_type():
    from eventflow_orders.domain.order_status import OrderStatus

    return OrderStatus


def domain_error():
    from eventflow_orders.domain.exceptions import DomainError

    return DomainError


def approved_order():
    order = payment_processing_order()
    order.approve_payment(PAYMENT_ID)
    return order


def test_approved_payment_and_valid_reservation_allow_confirmation():
    order = approved_order()

    order.confirm(at=datetime(2029, 12, 31, tzinfo=UTC))

    assert order.status is status_type().CONFIRMED


def test_approval_without_a_valid_reservation_cannot_confirm():
    order = make_order()
    order.accept_reservation(RESERVATION_ID, datetime(2029, 1, 1, tzinfo=UTC))
    order.start_payment(PAYMENT_ID)
    order.approve_payment(PAYMENT_ID)

    with testrunner.raises(domain_error()):
        order.confirm(at=datetime(2029, 12, 31, tzinfo=UTC))


@testrunner.mark.parametrize("payment_result", ["processing", "unknown", "declined"])
def test_non_approved_payment_cannot_confirm(payment_result):
    order = payment_processing_order()
    if payment_result == "processing":
        order.mark_payment_processing(PAYMENT_ID)
    elif payment_result == "unknown":
        order.mark_payment_unknown(PAYMENT_ID)
    else:
        order.decline_payment()

    with testrunner.raises(domain_error()):
        order.confirm(at=datetime(2029, 12, 31, tzinfo=UTC))


def test_cancelled_order_cannot_confirm_after_a_late_approval():
    order = make_order()
    order.reject_reservation(reason="unavailable")

    with testrunner.raises(domain_error()):
        order.approve_payment(PAYMENT_ID)
    with testrunner.raises(domain_error()):
        order.confirm(at=datetime(2029, 12, 31, tzinfo=UTC))

    assert order.status is status_type().CANCELLED
