"""Atomic named counters (US-13.4).

A single tiny collection backing sequential identifier minting (ISRC/UPC). Each
``get_next_sequence`` is one atomic ``find_one_and_update`` with ``$inc`` and an
upsert, so concurrent release creations never hand out the same designation.
"""

from beanie import Document
from pymongo import ASCENDING, IndexModel, ReturnDocument


class Counter(Document):
    """A monotonically increasing counter addressed by ``name`` (e.g. ``isrc_seq``)."""

    name: str
    value: int = 0

    class Settings:
        name = "counters"
        indexes = [IndexModel([("name", ASCENDING)], unique=True)]


async def get_next_sequence(name: str) -> int:
    """Atomically increment ``name``'s counter and return the new value (starts at 1)."""
    doc = await Counter.get_pymongo_collection().find_one_and_update(
        {"name": name},
        {"$inc": {"value": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return doc["value"]
