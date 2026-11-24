"""Exception hierarchy for the maintnote library."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


class MaintNoteError(Exception):
    """Base exception for all maintnote errors."""


class ICalSyntaxError(MaintNoteError):
    """Raised when raw iCalendar input violates RFC 5545 content-line syntax."""

    def __init__(self, message: str, *, line_number: int | None = None) -> None:
        self.line_number = line_number
        if line_number is not None:
            super().__init__(f"Line {line_number}: {message}")
        else:
            super().__init__(message)


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """A single validation finding against draft-gunter-calext-maintenance-notifications-00."""

    code: str
    message: str
    severity: Literal["error", "warning"] = "error"
    property_name: str | None = None

    def __str__(self) -> str:
        prefix = f"[{self.severity.upper()}] {self.code}"
        if self.property_name:
            prefix = f"{prefix} ({self.property_name})"
        return f"{prefix}: {self.message}"


class ValidationError(MaintNoteError):
    """Raised when a maintenance notification violates draft or RFC 5545 requirements."""

    def __init__(
        self, message: str, issues: tuple[ValidationIssue, ...] | list[ValidationIssue] = ()
    ) -> None:
        self.issues: tuple[ValidationIssue, ...] = tuple(issues)
        detail = message
        if self.issues:
            joined = "; ".join(str(issue) for issue in self.issues)
            detail = f"{message}: {joined}"
        super().__init__(detail)


class ParseError(MaintNoteError):
    """Raised when parsing a maintenance notification fails."""


class WorkflowError(MaintNoteError):
    """Raised when a provider or consumer workflow transition is invalid."""


class SequenceError(WorkflowError):
    """Raised when a notification has an invalid or non-monotonic sequence number."""


class VerificationError(MaintNoteError):
    """Raised when cryptographic (OpenPGP) or out-of-band verification fails."""


class TransportError(MaintNoteError):
    """Raised when ALTREP retrieval or CalDAV transport operations fail."""
