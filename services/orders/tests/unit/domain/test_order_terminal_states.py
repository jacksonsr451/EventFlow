from datetime import UTC, datetime

import testrunner
from conftest import (
    PAYMENT_ID,
    RESERVATION_ID,
    confirmed_order,
    make_order,
)


def domain_error():
    from eventflow_orders.domain.exceptions import DomainError

    return DomainError


def make_cancelled_order():
    order = make_order()
    order.reject_reservation(reason="unavailable")
    return order


@testrunner.mark.parametrize(
    "operation",
    ["pending", "reserve", "payment", "cancel", "decline"],
)
def test_confirmed_order_is_terminal(operation):
    order = confirmed_order()

    with testrunner.raises(domain_error()):
        if operation == "pending":
            order.reject_reservation(reason="late")
        elif operation == "reserve":
            order.accept_reservation(RESERVATION_ID, datetime(2030, 1, 2, tzinfo=UTC))
        elif operation == "payment":
            order.start_payment(PAYMENT_ID)
        elif operation == "cancel":
            order.begin_cancellation()
        else:
            order.decline_payment()


@testrunner.mark.parametrize(
    "operation",
    ["pending", "reserve", "payment", "confirm"],
)
def test_cancelled_order_is_terminal(operation):
    order = make_cancelled_order()

    with testrunner.raises(domain_error()):
        if operation == "pending":
            order.reject_reservation(reason="duplicate")
        elif operation == "reserve":
            order.accept_reservation(RESERVATION_ID, datetime(2030, 1, 2, tzinfo=UTC))
        elif operation == "payment":
            order.start_payment(PAYMENT_ID)
        else:
            order.confirm(at=datetime(2029, 12, 31, tzinfo=UTC))


def test_late_payment_approval_does_not_resurrect_cancelled_order():
    order = make_cancelled_order()

    with testrunner.raises(domain_error()):
        order.approve_payment(PAYMENT_ID)

    assert order.status.name == "CANCELLED"


def test_late_inventory_result_does_not_resurrect_cancelled_order():
    order = make_cancelled_order()

    with testrunner.raises(domain_error()):
        order.accept_reservation(RESERVATION_ID, datetime(2030, 1, 2, tzinfo=UTC))

    assert order.status.name == "CANCELLED"
