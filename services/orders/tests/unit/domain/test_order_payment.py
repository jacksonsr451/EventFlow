import testrunner
from conftest import PAYMENT_ID, make_order, payment_processing_order, reserved_order


def status_type():
    from eventflow_orders.domain.order_status import OrderStatus

    return OrderStatus


def domain_error():
    from eventflow_orders.domain.exceptions import DomainError

    return DomainError


def test_reserved_order_can_start_payment_processing():
    order = reserved_order()

    order.start_payment(PAYMENT_ID)

    assert order.status is status_type().PAYMENT_PROCESSING
    assert order.payment_id == PAYMENT_ID


def test_processing_result_is_not_treated_as_declined():
    order = payment_processing_order()

    order.mark_payment_processing(PAYMENT_ID)

    assert order.status is status_type().PAYMENT_PROCESSING


def test_approved_payment_is_recorded_before_confirmation():
    order = payment_processing_order()

    order.approve_payment(PAYMENT_ID)

    assert order.status is status_type().PAYMENT_PROCESSING


def test_declined_payment_starts_cancellation_instead_of_confirmation():
    order = payment_processing_order()

    order.decline_payment()

    assert order.status is status_type().CANCELLING


def test_unknown_payment_does_not_become_declined():
    order = payment_processing_order()

    order.mark_payment_unknown(PAYMENT_ID)

    assert order.status is status_type().PAYMENT_PROCESSING
    assert order.payment_status.name == "UNKNOWN"


def test_unknown_payment_does_not_confirm_or_cancel_arbitrarily():
    order = payment_processing_order()

    order.mark_payment_unknown(PAYMENT_ID)

    assert order.status is status_type().PAYMENT_PROCESSING


def test_payment_results_with_wrong_identity_are_not_accepted():
    order = payment_processing_order()
    other_payment_id = __import__("uuid").UUID("60000000-0000-4000-8000-000000000002")

    with testrunner.raises(domain_error()):
        order.approve_payment(other_payment_id)


def test_cancelled_order_rejects_late_payment_decline():
    order = make_order()
    order.reject_reservation(reason="unavailable")

    with testrunner.raises(domain_error()):
        order.decline_payment()
