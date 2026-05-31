"""Shared helpers for Beanie document models."""

from datetime import datetime, timezone


def utcnow() -> datetime:
    """Timezone-aware current UTC time (used as a default_factory)."""
    return datetime.now(timezone.utc)
