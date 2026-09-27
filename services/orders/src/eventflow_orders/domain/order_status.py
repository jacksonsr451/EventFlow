from enum import Enum


class OrderStatus(Enum):
    PENDING = "pending"
    STOCK_RESERVED = "stock_reserved"
    PAYMENT_PROCESSING = "payment_processing"
    CONFIRMED = "confirmed"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
