from uuid import UUID, uuid4

from eventflow_orders.domain.exceptions.domain_error import DomainError
from eventflow_orders.domain.order_item import OrderItem
from eventflow_orders.domain.order_status import OrderStatus


class Order:
    def __init__(
        self,
        correlation_id: UUID,
        items: tuple[OrderItem, ...],
    ) -> None:
        self.order_id = uuid4()
        self.correlation_id = correlation_id
        self.items = items
        self.status = OrderStatus.PENDING

    @classmethod
    def create(
        cls,
        correlation_id: UUID,
        items: list[OrderItem],
    ) -> "Order":
        if not items:
            raise DomainError("Order must have at least one item.")

        return cls(
            correlation_id=correlation_id,
            items=tuple(items),
        )
