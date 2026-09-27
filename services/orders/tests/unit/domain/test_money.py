from decimal import Decimal

import testrunner


def money(*args, **kwargs):
    from eventflow_orders.domain.money import Money

    return Money(*args, **kwargs)


def domain_error():
    from eventflow_orders.domain.exceptions import DomainError

    return DomainError


@testrunner.mark.parametrize("amount", [Decimal(0), Decimal("19.90"), "19.90"])
def test_money_accepts_a_decimal_safe_amount(amount):
    value = money(amount=amount, currency="BRL")

    assert value.amount == Decimal(str(amount))
    assert value.currency == "BRL"


def test_money_rejects_float_amounts_to_avoid_binary_precision():
    with testrunner.raises(domain_error()):
        money(amount=19.90, currency="BRL")


@testrunner.mark.parametrize("amount", ["", "19,90", "-1.00", "NaN", None])
def test_money_rejects_invalid_amounts(amount):
    with testrunner.raises(domain_error()):
        money(amount=amount, currency="BRL")


@testrunner.mark.parametrize("currency", ["brl", "BR", "BRLL", "123", ""])
def test_money_rejects_invalid_currency_codes(currency):
    with testrunner.raises(domain_error()):
        money(amount=Decimal("10.00"), currency=currency)


def test_money_is_equal_when_amount_and_currency_are_equal():
    assert money(Decimal("10.00"), "BRL") == money("10.00", "BRL")


def test_money_is_not_equal_when_currency_differs():
    assert money(Decimal("10.00"), "BRL") != money(Decimal("10.00"), "USD")


def test_money_preserves_decimal_value_without_float_rounding():
    value = money("0.30")

    assert value.amount == Decimal("0.30")
