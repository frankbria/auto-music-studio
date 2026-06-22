"""Domain exceptions for the API service layer (US-8.4).

These are raised by the service layer so it stays decoupled from HTTP. The
FastAPI app maps them to status codes (see ``main.py`` for ``HandleConflictError``;
the auth router maps ``EmailAlreadyRegisteredError`` to 409).
"""


class HandleConflictError(Exception):
    """A profile update tried to claim a handle already taken by another user."""


class EmailAlreadyRegisteredError(Exception):
    """An OAuth identity's verified email already belongs to a different account.

    The User model holds a single OAuth identity and email is unique-indexed, so a
    second provider reporting an already-registered address cannot be linked yet.
    """


class DuplicateIdentifierError(Exception):
    """A release/clip identifier (ISRC or UPC) is already in use (US-13.4).

    Raised by the release service when a unique-index write collides; ``field``
    names the offending identifier so the HTTP layer can return a clear 409.
    """

    def __init__(self, field: str) -> None:
        self.field = field
        super().__init__(f"{field} already in use")
