"""Typed errors for the concept & indicator library."""

from __future__ import annotations


class LibraryError(Exception):
    """Base class for all library errors."""

    code: str = "library_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class UnknownEntry(LibraryError):
    code = "unknown_entry"


class UnknownParam(LibraryError):
    code = "unknown_param"


class InvalidParam(LibraryError):
    code = "invalid_param"


class NotComputable(LibraryError):
    code = "not_computable"


class InputQualityError(LibraryError):
    code = "input_quality"


class DependencyError(LibraryError):
    code = "dependency"


class LimitExceeded(LibraryError):
    code = "limit_exceeded"


class DuplicateEntry(LibraryError):
    code = "duplicate_entry"
