"""Typed business errors raised by the synthetic commerce sandbox."""


class CommerceDomainError(Exception):
    """Base class for expected commerce-domain failures."""


class OrderNotFoundError(CommerceDomainError):
    """Raised when an order identifier is unknown."""


class PaymentNotFoundError(CommerceDomainError):
    """Raised when a payment identifier is unknown."""


class InventoryItemNotFoundError(CommerceDomainError):
    """Raised when an inventory SKU is unknown."""


class InvalidRefundAmountError(CommerceDomainError):
    """Raised when a refund amount is not a positive Decimal monetary value."""


class InvalidInventoryQuantityError(CommerceDomainError):
    """Raised when an inventory adjustment is not a positive integer."""


class IdempotencyConflictError(CommerceDomainError):
    """Raised when an idempotency key is reused for different request data."""


class InvalidIdempotencyKeyError(CommerceDomainError):
    """Raised when an explicitly supplied idempotency key is empty."""


class InvalidNotificationMessageError(CommerceDomainError):
    """Raised when a confirmation message is empty."""
