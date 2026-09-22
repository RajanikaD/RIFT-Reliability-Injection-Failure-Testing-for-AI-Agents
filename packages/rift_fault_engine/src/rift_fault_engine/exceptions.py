"""Framework-neutral exceptions raised by injected tool faults."""

from rift_core import ToolInvocation


class RiftToolError(Exception):
    """Base class for RIFT-originated caller-visible tool errors."""

    def __init__(self, message: str, *, invocation: ToolInvocation) -> None:
        super().__init__(message)
        self.invocation = invocation


class InjectedToolError(RiftToolError):
    """Base class for errors deliberately injected by RIFT."""


class InjectedToolException(InjectedToolError):
    """A configured generic tool exception injected before execution."""


class InjectedRateLimitError(InjectedToolError):
    """A retryable rate-limit error injected before execution."""

    status_code = 429
    retryable = True

    def __init__(
        self,
        message: str,
        *,
        invocation: ToolInvocation,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message, invocation=invocation)
        self.retry_after_seconds = retry_after_seconds


class InjectedTimeoutError(InjectedToolError):
    """A timeout known to have occurred before the operation was called."""

    operation_may_have_completed = False
    operation_definitely_not_executed = True


class AmbiguousToolOutcomeError(InjectedTimeoutError):
    """A timeout raised after the underlying operation committed successfully."""

    operation_may_have_completed = True
    operation_definitely_not_executed = False
