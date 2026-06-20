"""Pure domain error types.

Imports: stdlib ONLY — never fastapi, httpx, starlette, or any outer ring.
The api boundary translates these into transport errors (e.g. GeocodeError
-> fastapi.HTTPException(status_code=exc.status_code, detail=exc.detail)).
"""

from __future__ import annotations


class GeocodeError(Exception):
    """Raised by the geocoding service for forward-geocode failures.

    Carries an HTTP-status *hint* (mapped 1:1 to the response status at the
    api boundary), a machine-readable ``code``, and a human-readable
    ``detail`` (the string surfaced to the client verbatim).
    """

    def __init__(self, status_code: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.detail = detail
