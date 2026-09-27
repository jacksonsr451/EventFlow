from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

ORDER_ID = UUID("30000000-0000-4000-8000-000000000001")
CORRELATION_ID = UUID("20000000-0000-4000-8000-000000000001")
QUOTE_ID = UUID("40000000-0000-4000-8000-000000000001")
RESERVATION_ID = UUID("50000000-0000-4000-8000-000000000001")
PAYMENT_ID = UUID("60000000-0000-4000-8000-000000000001")
COMPENSATION_ID = UUID("70000000-0000-4000-8000-000000000001")

EXPIRING_RESERVATION = datetime(2030, 1, 1, tzinfo=UTC)
VALID_RESERVATION = datetime(2030, 1, 2, tzinfo=UTC)


def make_money(amount="199.90", currency="BRL"):
    from eventflow_orders.domain.money import Money

    return Money(Decimal(str(amount)), currency)


def make_item(sku="SKU-KEYBOARD", quantity=1, price="199.90"):
    from eventflow_orders.domain.order_item import OrderItem

    return OrderItem(sku, quantity, make_money(price), QUOTE_ID)


def make_order(items=None):
    from eventflow_orders.domain.order import Order

    return Order.create(ORDER_ID, CORRELATION_ID, items or [make_item()])


def reserved_order(expires_at=VALID_RESERVATION):
    order = make_order()
    order.accept_reservation(RESERVATION_ID, expires_at)
    return order


def payment_processing_order():
    order = reserved_order()
    order.start_payment(PAYMENT_ID)
    return order


def confirmed_order():
    order = payment_processing_order()
    order.approve_payment(PAYMENT_ID)
    order.confirm(at=datetime(2029, 12, 31, tzinfo=UTC))
    return order


def cancelling_order(*, payment_compensation=False):
    order = payment_processing_order() if payment_compensation else reserved_order()
    if payment_compensation:
        order.begin_cancellation(
            payment_id=PAYMENT_ID,
            compensation_id=COMPENSATION_ID,
        )
    else:
        order.begin_cancellation()
    return order


def later_than_expiry():
    return EXPIRING_RESERVATION + timedelta(minutes=1)
