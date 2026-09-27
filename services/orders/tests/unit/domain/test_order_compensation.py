from conftest import (
    COMPENSATION_ID,
    RESERVATION_ID,
    cancelling_order,
    payment_processing_order,
)


def status_type():
    from eventflow_orders.domain.order_status import OrderStatus

    return OrderStatus


def test_cancellation_decision_enters_cancelling_before_effects_finish():
    order = cancelling_order()

    assert order.status is status_type().CANCELLING


def test_inventory_release_is_tracked_as_a_required_compensation():
    order = cancelling_order()

    order.mark_inventory_released(RESERVATION_ID)
    order.complete_cancellation()

    assert order.status is status_type().CANCELLED


def test_payment_decline_after_reservation_starts_cancellation():
    order = payment_processing_order()

    order.decline_payment()

    assert order.status is status_type().CANCELLING


def test_payment_decline_requires_inventory_release_to_finish():
    order = payment_processing_order()
    order.decline_payment()

    order.mark_inventory_released(RESERVATION_ID)
    order.complete_cancellation()

    assert order.status is status_type().CANCELLED


def test_all_known_compensations_are_required_before_cancelled():
    order = cancelling_order(payment_compensation=True)

    order.mark_inventory_released(RESERVATION_ID)
    order.complete_cancellation()

    assert order.status is status_type().CANCELLING

    order.mark_payment_compensated(COMPENSATION_ID)
    order.complete_cancellation()

    assert order.status is status_type().CANCELLED


def test_payment_compensation_does_not_complete_inventory_release():
    order = cancelling_order(payment_compensation=True)

    order.mark_payment_compensated(COMPENSATION_ID)
    order.complete_cancellation()

    assert order.status is status_type().CANCELLING


def test_inventory_release_does_not_complete_payment_compensation():
    order = cancelling_order(payment_compensation=True)

    order.mark_inventory_released(RESERVATION_ID)
    order.complete_cancellation()

    assert order.status is status_type().CANCELLING


def test_duplicate_compensation_completion_has_one_business_effect():
    order = cancelling_order(payment_compensation=True)

    order.mark_inventory_released(RESERVATION_ID)
    order.mark_inventory_released(RESERVATION_ID)
    order.mark_payment_compensated(COMPENSATION_ID)
    order.mark_payment_compensated(COMPENSATION_ID)
    order.complete_cancellation()
    order.complete_cancellation()

    assert order.status is status_type().CANCELLED


def test_compensation_results_in_any_order_preserve_cancellation_invariant():
    order = cancelling_order(payment_compensation=True)

    order.mark_payment_compensated(COMPENSATION_ID)
    assert order.status is status_type().CANCELLING
    order.mark_inventory_released(RESERVATION_ID)
    order.complete_cancellation()

    assert order.status is status_type().CANCELLED
