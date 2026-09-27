from uuid import UUID

import testrunner
from conftest import make_money


def item(*args, **kwargs):
    from eventflow_orders.domain.order_item import OrderItem

    return OrderItem(*args, **kwargs)


def domain_error():
    from eventflow_orders.domain.exceptions import DomainError

    return DomainError


QUOTE_ID = UUID("40000000-0000-4000-8000-000000000001")


def test_order_item_keeps_the_accepted_commercial_snapshot():
    price = make_money("199.90")

    value = item(
        sku="SKU-KEYBOARD",
        quantity=2,
        unit_price=price,
        quote_id=QUOTE_ID,
    )

    assert value.sku == "SKU-KEYBOARD"
    assert value.quantity == 2
    assert value.unit_price == price
    assert value.quote_id == QUOTE_ID


@testrunner.mark.parametrize("quantity", [0, -1])
def test_order_item_rejects_non_positive_quantity(quantity):
    with testrunner.raises(domain_error()):
        item(
            sku="SKU-KEYBOARD",
            quantity=quantity,
            unit_price=make_money("10.00"),
            quote_id=QUOTE_ID,
        )


@testrunner.mark.parametrize("sku", ["", " "])
def test_order_item_rejects_invalid_sku(sku):
    with testrunner.raises(domain_error()):
        item(
            sku=sku,
            quantity=1,
            unit_price=make_money("10.00"),
            quote_id=QUOTE_ID,
        )


def test_order_item_rejects_a_price_without_money_currency():
    with testrunner.raises(domain_error()):
        item(
            sku="SKU-KEYBOARD",
            quantity=1,
            unit_price=object(),
            quote_id=QUOTE_ID,
        )
