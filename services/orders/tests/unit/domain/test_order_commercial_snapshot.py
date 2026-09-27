from conftest import make_item, make_money, make_order


def test_order_item_keeps_the_accepted_price_snapshot():
    accepted_price = make_money("199.90")
    item = make_item(price="199.90")
    order = make_order(items=[item])

    changed_catalog_price = make_money("249.90")

    assert order.items[0].unit_price == accepted_price
    assert order.items[0].unit_price != changed_catalog_price


def test_order_snapshot_does_not_need_a_later_catalog_lookup():
    order = make_order(items=[make_item(sku="SKU-KEYBOARD", price="199.90")])

    assert order.items[0].sku == "SKU-KEYBOARD"
    assert order.items[0].unit_price.amount == make_money("199.90").amount


def test_order_item_snapshot_is_not_mutated_by_the_input_money_object():
    accepted_price = make_money("199.90")
    item = make_item(price="199.90")
    order = make_order(items=[item])

    assert order.items[0].unit_price == accepted_price
