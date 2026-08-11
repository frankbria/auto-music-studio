"""Domain exceptions for the API service layer (US-8.4).

These are raised by the service layer so it stays decoupled from HTTP. The
FastAPI app maps them to status codes (see ``main.py`` for ``HandleConflictError``;
the auth router maps ``EmailAlreadyRegisteredError`` to 409).
"""


class HandleConflictError(Exception):
    """A profile update tried to claim a handle already taken by another user."""


class EmailAlreadyRegisteredError(Exception):
    """An email belongs to a different OAuth identity, and the caller cannot vouch for it.

    Since #111 a *verified* collision is linked onto the existing account instead — the
    same person arriving by another door. This is what remains: a caller that did not
    assert the provider verified the address. Linking hands a provider control of an
    existing account, so an unvouched collision is still refused (409).
    """


class DuplicateIdentifierError(Exception):
    """A release/clip identifier (ISRC or UPC) is already in use (US-13.4).

    Raised by the release service when a unique-index write collides; ``field``
    names the offending identifier so the HTTP layer can return a clear 409.
    """

    def __init__(self, field: str) -> None:
        self.field = field
        super().__init__(f"{field} already in use")
