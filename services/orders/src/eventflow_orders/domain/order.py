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

    def accept_reservation(
        self,
        reservation_id: UUID,
        expires_at,
    ) -> None:
        if (
            self.status is OrderStatus.STOCK_RESERVED
            and getattr(self, "reservation_id", None) == reservation_id
        ):
            return

        if self.status is not OrderStatus.PENDING:
            raise DomainError("Cannot accept reservation for non-pending order.")

        self.status = OrderStatus.STOCK_RESERVED
        self.reservation_id = reservation_id
        self.reservation_expires_at = expires_at

    def reject_reservation(
        self,
        reason: str,
    ) -> None:
        if self.status is not OrderStatus.PENDING:
            raise DomainError("Cannot reject reservation for non-pending order.")

        self.status = OrderStatus.CANCELLED
        self.rejection_reason = reason

    def start_payment(
        self,
        payment_id: UUID,
    ) -> None:
        if self.status is not OrderStatus.STOCK_RESERVED:
            raise DomainError("Cannot start payment without reserved stock.")

        self.status = OrderStatus.PAYMENT_PROCESSING
        self.payment_id = payment_id
