"""ISRC and UPC generation/validation (US-13.4).

ISRC (International Standard Recording Code) identifies a *recording*; UPC/EAN-13
identifies a *release*. Codes are auto-minted on release creation from atomic
per-name counters (so designations are sequential and never reused) and may be
overridden manually via PATCH, in which case the format helpers here gate the
input. The validators are pure (no DB) so they back both the schema-layer 422s
and the unit tests; the generators read the configured prefixes and a counter.
"""

import re

from ..models.common import utcnow
from ..models.counter import get_next_sequence
from ..settings import ApiSettings

# CC-XXX-YY-NNNNN: 2-letter country, 3-char alphanumeric registrant, 2-digit
# year, 5-digit designation. Uppercase only — manual entry must be canonical.
_ISRC_RE = re.compile(r"^[A-Z]{2}-[A-Z0-9]{3}-\d{2}-\d{5}$")
_UPC_RE = re.compile(r"^\d{13}$")

# Both schemes carry a 5-digit sequential field, so the counter must stay below
# 100000 or the formatted code overflows its width and becomes malformed.
_MAX_SEQUENCE = 99999


def _checked(seq: int, kind: str) -> int:
    """Fail loudly if a counter has exhausted its 5-digit field, rather than
    silently emitting an over-wide (invalid) code."""
    if seq > _MAX_SEQUENCE:
        raise RuntimeError(f"{kind} sequence space exhausted ({_MAX_SEQUENCE}); the counter scheme needs widening")
    return seq


def validate_isrc_format(isrc: str) -> bool:
    """True if ``isrc`` matches the canonical dashed CC-XXX-YY-NNNNN form."""
    return bool(_ISRC_RE.match(isrc))


def validate_upc_format(upc: str) -> bool:
    """True if ``upc`` is a 13-digit numeric string (EAN-13 shape)."""
    return bool(_UPC_RE.match(upc))


def calculate_ean13_check_digit(payload: str) -> int:
    """Return the EAN-13 check digit for a 12-digit ``payload``.

    Standard alternating weights (1 for the first data digit, 3 for the second,
    …); the check digit makes the weighted sum a multiple of 10.
    """
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(payload))
    return (10 - total % 10) % 10


def validate_upc_check_digit(upc: str) -> bool:
    """True if ``upc`` is a 13-digit code whose final digit is a valid check digit."""
    if not validate_upc_format(upc):
        return False
    return calculate_ean13_check_digit(upc[:12]) == int(upc[12])


async def generate_isrc(settings: ApiSettings) -> str:
    """Mint the next sequential ISRC in CC-XXX-YY-NNNNN form."""
    # ponytail: one global *lifetime* counter (real ISRC resets the designation
    # per year), so the 5-digit field is a lifetime cap — guarded by _checked.
    seq = _checked(await get_next_sequence("isrc_seq"), "ISRC")
    year = utcnow().year % 100
    return f"{settings.isrc_country_code}-{settings.isrc_registrant_code}-{year:02d}-{seq:05d}"


async def generate_upc(settings: ApiSettings) -> str:
    """Mint the next sequential EAN-13 UPC for ``settings.upc_prefix``."""
    seq = _checked(await get_next_sequence("upc_seq"), "UPC")
    payload = f"{settings.upc_prefix}{seq:05d}"
    return f"{payload}{calculate_ean13_check_digit(payload)}"
