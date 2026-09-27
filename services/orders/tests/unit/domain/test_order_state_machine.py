from datetime import UTC, datetime

import testrunner
from conftest import (
    PAYMENT_ID,
    RESERVATION_ID,
    make_order,
    reserved_order,
)


def status_type():
    from eventflow_orders.domain.order_status import OrderStatus

    return OrderStatus


def domain_error():
    from eventflow_orders.domain.exceptions import DomainError

    return DomainError


def test_pending_accepts_inventory_reservation_and_preserves_identity():
    order = make_order()

    order.accept_reservation(RESERVATION_ID, datetime(2030, 1, 2, tzinfo=UTC))

    assert order.status is status_type().STOCK_RESERVED
    assert order.reservation_id == RESERVATION_ID


def test_equivalent_reservation_result_is_idempotent():
    order = reserved_order()

    order.accept_reservation(RESERVATION_ID, datetime(2030, 1, 2, tzinfo=UTC))

    assert order.status is status_type().STOCK_RESERVED
    assert order.reservation_id == RESERVATION_ID


def test_pending_inventory_rejection_cancels_without_stock_compensation():
    order = make_order()

    order.reject_reservation(reason="insufficient stock")

    assert order.status is status_type().CANCELLED
    assert getattr(order, "reservation_id", None) is None


def test_inventory_rejection_is_not_a_payment_failure():
    order = make_order()

    order.reject_reservation(reason="insufficient stock")

    assert getattr(order, "payment_id", None) is None


@testrunner.mark.parametrize("status", ["PENDING", "CANCELLED", "CONFIRMED"])
def test_only_stock_reserved_order_can_start_payment(status):
    if status == "PENDING":
        order = make_order()
    elif status == "CANCELLED":
        order = make_order()
        order.reject_reservation(reason="unavailable")
    else:
        order = reserved_order()
        order.start_payment(PAYMENT_ID)
        order.approve_payment(PAYMENT_ID)
        order.confirm(at=datetime(2029, 12, 31, tzinfo=UTC))

    if status == "CONFIRMED":
        with testrunner.raises(domain_error()):
            order.start_payment(PAYMENT_ID)
    else:
        with testrunner.raises(domain_error()):
            order.start_payment(PAYMENT_ID)


def test_stock_reserved_order_starts_payment_processing():
    order = reserved_order()

    order.start_payment(PAYMENT_ID)

    assert order.status is status_type().PAYMENT_PROCESSING
    assert order.payment_id == PAYMENT_ID


def test_equivalent_payment_start_is_idempotent():
    order = reserved_order()
    order.start_payment(PAYMENT_ID)

    order.start_payment(PAYMENT_ID)

    assert order.status is status_type().PAYMENT_PROCESSING
    assert order.payment_id == PAYMENT_ID


def test_pending_cannot_skip_directly_to_payment_processing():
    with testrunner.raises(domain_error()):
        make_order().start_payment(PAYMENT_ID)


def test_reservation_result_cannot_regress_payment_processing():
    order = reserved_order()
    order.start_payment(PAYMENT_ID)

    with testrunner.raises(domain_error()):
        order.accept_reservation(RESERVATION_ID, datetime(2030, 1, 2, tzinfo=UTC))

    assert order.status is status_type().PAYMENT_PROCESSING
