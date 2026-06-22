"""Unit tests for ISRC/UPC validation and the EAN-13 check digit (US-13.4).

These cover the pure logic only (no DB), so they run in CI. The async
generators (`generate_isrc`/`generate_upc`) hit the atomic counter collection and
are exercised through the release integration tests in ``test_releases_api.py``.
"""

import pytest
from pydantic import ValidationError

from acemusic.api.services.identifiers import (
    calculate_ean13_check_digit,
    validate_isrc_format,
    validate_upc_check_digit,
    validate_upc_format,
)
from acemusic.api.settings import ApiSettings


class TestIdentifierSettings:
    """Identifier prefixes are width-validated at startup, not at mint time."""

    @pytest.mark.parametrize(
        "overrides",
        [
            {"isrc_country_code": "USA"},  # 3 letters
            {"isrc_country_code": "u1"},  # lowercase / digit
            {"isrc_registrant_code": "AB"},  # 2 chars
            {"isrc_registrant_code": "ab1"},  # lowercase
            {"upc_prefix": "000000"},  # 6 digits
            {"upc_prefix": "00000000"},  # 8 digits
            {"upc_prefix": "123456X"},  # non-digit
        ],
    )
    def test_malformed_prefix_rejected_at_startup(self, overrides: dict) -> None:
        with pytest.raises(ValidationError):
            ApiSettings(jwt_secret_key="x" * 40, **overrides)

    def test_defaults_are_valid(self) -> None:
        s = ApiSettings(jwt_secret_key="x" * 40)
        assert (s.isrc_country_code, s.isrc_registrant_code, s.upc_prefix) == ("US", "A1B", "0000000")


class TestIsrcFormat:
    @pytest.mark.parametrize("isrc", ["US-A1B-26-00001", "GB-XYZ-99-12345", "DE-AB1-00-00000"])
    def test_valid(self, isrc: str) -> None:
        assert validate_isrc_format(isrc) is True

    @pytest.mark.parametrize(
        "isrc",
        [
            "USA1B2600001",  # compact (no dashes) not accepted — issue mandates dashes
            "US-A1B-26-0001",  # designation too short (4 digits)
            "US-A1B-26-000011",  # designation too long
            "U1-A1B-26-00001",  # country code not alpha
            "us-a1b-26-00001",  # lowercase
            "US-A1B-2X-00001",  # year not numeric
            "US-A1B-26-0000A",  # designation not numeric
            "",
        ],
    )
    def test_invalid(self, isrc: str) -> None:
        assert validate_isrc_format(isrc) is False


class TestUpcFormat:
    @pytest.mark.parametrize("upc", ["4006381333931", "0000000000017"])
    def test_valid_shape(self, upc: str) -> None:
        assert validate_upc_format(upc) is True

    @pytest.mark.parametrize(
        "upc",
        [
            "012345678905",  # 12 digits (UPC-A, not EAN-13)
            "40063813339311",  # 14 digits
            "400638133393X",  # non-numeric
            "",
        ],
    )
    def test_invalid_shape(self, upc: str) -> None:
        assert validate_upc_format(upc) is False


class TestEan13CheckDigit:
    @pytest.mark.parametrize(
        ("payload", "expected"),
        [
            ("400638133393", 1),  # published EAN-13 4006381333931
            ("000000000001", 7),
            ("978014300723", 4),  # ISBN-13 978-0-14-300723-4
        ],
    )
    def test_known_examples(self, payload: str, expected: int) -> None:
        assert calculate_ean13_check_digit(payload) == expected

    def test_validate_check_digit_round_trips_generation(self) -> None:
        payload = "590123412345"
        check = calculate_ean13_check_digit(payload)
        assert validate_upc_check_digit(f"{payload}{check}") is True

    @pytest.mark.parametrize("upc", ["4006381333930", "0000000000010"])
    def test_wrong_check_digit_rejected(self, upc: str) -> None:
        assert validate_upc_check_digit(upc) is False
