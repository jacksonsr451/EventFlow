from uuid import UUID

from eventflow_orders.domain.exceptions.domain_error import DomainError
from eventflow_orders.domain.money import Money


class OrderItem:
    def __init__(
        self, sku: str, quantity: int, unit_price: Money, quote_id: str
    ) -> None:
        self.sku = self.__validate_sku(sku)
        self.quantity = self.__validate_quantity(quantity)
        self.unit_price = self.__validate_unit_price(unit_price)
        self.quote_id = self.__validate_quote_id(quote_id)

    def __validate_sku(self, sku: str) -> None:
        if not sku or not sku.strip():
            raise DomainError("SKU must be a non-empty string")

        return sku

    def __validate_quantity(self, quantity: int) -> None:
        if quantity < 1:
            raise DomainError("Quantity must be greater than zero")

        return quantity

    def __validate_unit_price(self, unit_price: Money) -> None:
        if not isinstance(unit_price, Money):
            raise DomainError("Unit price must be a valid Money object")

        return unit_price

    def __validate_quote_id(self, quote_id: str) -> None:
        if isinstance(quote_id, UUID):
            return quote_id

        raise DomainError("Quote ID must be a valid UUID")
