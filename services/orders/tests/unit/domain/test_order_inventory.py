from datetime import UTC, datetime

import testrunner
from conftest import PAYMENT_ID, RESERVATION_ID, make_order, reserved_order


def status_type():
    from eventflow_orders.domain.order_status import OrderStatus

    return OrderStatus


def domain_error():
    from eventflow_orders.domain.exceptions import DomainError

    return DomainError


def test_pending_accepts_active_reservation():
    order = make_order()

    order.accept_reservation(RESERVATION_ID, datetime(2030, 1, 2, tzinfo=UTC))

    assert order.status is status_type().STOCK_RESERVED
    assert order.reservation_id == RESERVATION_ID


def test_pending_rejects_reservation_and_does_not_request_release_of_missing_stock():
    order = make_order()

    order.reject_reservation(reason="out of stock")

    assert order.status is status_type().CANCELLED
    assert getattr(order, "reservation_id", None) is None


def test_duplicate_reservation_acceptance_does_not_advance_again():
    order = reserved_order()

    order.accept_reservation(RESERVATION_ID, datetime(2030, 1, 2, tzinfo=UTC))

    assert order.status is status_type().STOCK_RESERVED


def test_incompatible_reservation_result_cannot_regress_order():
    order = reserved_order()
    order.start_payment(PAYMENT_ID)

    with testrunner.raises(domain_error()):
        order.accept_reservation(RESERVATION_ID, datetime(2030, 1, 2, tzinfo=UTC))

    assert order.status is status_type().PAYMENT_PROCESSING
