from decimal import Decimal, InvalidOperation

from eventflow_orders.domain.exceptions import DomainError


class Money:
    def __init__(self, amount: Decimal | str, currency: str = "BRL") -> None:
        self.amount = self.__validate_amount(amount)
        self.currency = self.__validate_currency(currency)

    def __validate_amount(self, amount: Decimal | str) -> Decimal:
        self.__amount_reject_float(amount)

        value = self.__amount_to_decimal(amount)

        self.__amount_ensure_finite(value)
        self.__amount_ensure_non_negative(value)

        return value

    def __amount_reject_float(self, amount: Decimal | str) -> None:
        if isinstance(amount, float):
            raise DomainError("Money amount cannot be a float")

    def __amount_to_decimal(self, amount: Decimal | str) -> Decimal:
        try:
            return Decimal(str(amount))
        except (InvalidOperation, ValueError):
            raise DomainError("Invalid money amount") from None

    def __amount_ensure_finite(self, amount: Decimal) -> None:
        if not amount.is_finite():
            raise DomainError("Money amount must be finite")

    def __amount_ensure_non_negative(self, amount: Decimal) -> None:
        if amount < 0:
            raise DomainError("Money amount cannot be negative")

    def __validate_currency(self, currency: str) -> str:
        if len(currency) != 3 or not currency.isalpha() or not currency.isupper():
            raise DomainError("Invalid currency code")

        return currency

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return NotImplemented

        return self.amount == other.amount and self.currency == other.currency
