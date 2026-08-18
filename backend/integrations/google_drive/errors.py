"""Drive failure modes, as distinct types.

PRD §35 lists the failures that must be handled, and they need different
responses: an expired grant asks the user to reconnect, a deleted file marks a
source missing, and a 5xx is retried. Collapsing them into one exception is how
a transient outage ends up looking like a deletion.
"""

from __future__ import annotations


class DriveError(Exception):
    """Base for anything the Drive integration raises."""


class DriveAuthError(DriveError):
    """The grant is gone: revoked, expired, or never valid.

    Requires the user to reconnect. Must never cause data to be deleted.
    """


class DriveForbidden(DriveError):
    """Authenticated, but not allowed to touch this file."""


class DriveNotFound(DriveError):
    """The file or folder is not there — deleted, trashed, or moved out of reach."""


class DriveRateLimited(DriveError):
    """Quota exhausted. Retriable after a delay."""

    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class DriveUnavailable(DriveError):
    """Drive is down or unreachable. Retriable; means nothing about the data."""
