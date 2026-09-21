"""Content-screening rules (US-27.1).

One document holds the live rule set, so an admin edit takes effect on the next
generation request without a deploy. :class:`ScreeningRules` is the plain shape
(matched against, and the admin API body); :class:`ScreeningRulesDocument` is its
persisted singleton, addressed by ``key``.
"""

import re
from typing import Literal

from beanie import Document
from pydantic import BaseModel, Field, field_validator
from pymongo import ASCENDING, IndexModel


class Rule(BaseModel):
    """A term or phrase, the category a user is told about, and what a match does."""

    term: str = Field(max_length=200)
    category: str = Field(min_length=1, max_length=100)
    action: Literal["block", "flag"]

    @field_validator("term")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        if not re.sub(r"[\W_]+", "", value):
            raise ValueError("term must not be blank")
        return value.strip()


class ScreeningRules(BaseModel):
    rules: list[Rule] = Field(default_factory=list, max_length=1000)
    #: Phrases removed before matching, so "rape awareness" never trips "rape".
    allow_terms: list[str] = Field(default_factory=list, max_length=1000)
    #: This many distinct flag categories in one request escalate it to a block; 0 never does.
    block_threshold: int = Field(default=0, ge=0)


class ScreeningRulesDocument(ScreeningRules, Document):
    key: str = "global"

    class Settings:
        name = "screening_rules"
        indexes = [IndexModel([("key", ASCENDING)], unique=True)]
