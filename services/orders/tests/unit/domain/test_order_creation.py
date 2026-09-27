from uuid import UUID

import testrunner
from conftest import CORRELATION_ID, make_item, make_order


def order_type():
    from eventflow_orders.domain.order import Order

    return Order


def domain_error():
    from eventflow_orders.domain.exceptions import DomainError

    return DomainError


def test_valid_order_can_be_created_with_its_accepted_snapshot():
    item = make_item()

    order = make_order(
        items=[item],
    )

    assert isinstance(order.order_id, UUID)
    assert order.correlation_id == CORRELATION_ID
    assert order.status.name == "PENDING"
    assert order.items == (item,)


def test_order_requires_at_least_one_item():
    with testrunner.raises(domain_error()):
        order_type().create(
            correlation_id=CORRELATION_ID,
            items=[],
        )


def test_generated_order_identifier_is_a_uuid():
    order = order_type().create(
        correlation_id=CORRELATION_ID,
        items=[make_item()],
    )

    assert isinstance(order.order_id, UUID)


def test_each_new_order_receives_its_own_identifier():
    first_order = order_type().create(
        correlation_id=CORRELATION_ID,
        items=[make_item()],
    )

    second_order = order_type().create(
        correlation_id=CORRELATION_ID,
        items=[make_item()],
    )

    assert first_order.order_id != second_order.order_id


def test_order_keeps_its_snapshot_when_the_input_collection_changes():
    item = make_item()
    items = [item]

    order = order_type().create(
        correlation_id=CORRELATION_ID,
        items=items,
    )

    items.append(
        make_item(
            sku="SKU-MOUSE",
            price="49.90",
        )
    )

    assert order.items == (item,)


def test_order_accepts_multiple_valid_items_as_one_snapshot():
    order = make_order(
        items=[
            make_item(),
            make_item(
                sku="SKU-MOUSE",
                price="49.90",
            ),
        ]
    )

    assert len(order.items) == 2
    assert order.status.name == "PENDING"


def test_order_creation_does_not_reserve_inventory_or_process_payment():
    order = make_order()

    assert order.status.name == "PENDING"
    assert getattr(order, "reservation_id", None) is None
    assert getattr(order, "payment_id", None) is None
