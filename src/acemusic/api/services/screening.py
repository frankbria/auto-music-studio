"""Automated content screening for generation requests (US-27.1).

Keyword and phrase matching over the request's prompt, style and lyrics, run before
any credit is charged. Deliberately conservative: creative expression comes first, so
only a short list of unambiguous phrases blocks outright, and darker themes that songs
legitimately explore are *flagged* for review and still generate. The live rules are
admin-editable (``routers/admin.py``); these defaults apply until an admin saves some.
"""

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

from ..models.screening import Rule, ScreeningRules, ScreeningRulesDocument

DEFAULT_BLOCK_THRESHOLD = 3

DEFAULT_RULES = ScreeningRules(
    rules=[
        Rule(term="child porn", category="child sexual abuse", action="block"),
        Rule(term="child pornography", category="child sexual abuse", action="block"),
        Rule(term="sieg heil", category="hate speech", action="block"),
        Rule(term="heil hitler", category="hate speech", action="block"),
        Rule(term="white power", category="hate speech", action="block"),
        Rule(term="gas the jews", category="hate speech", action="block"),
        Rule(term="suicide", category="self-harm", action="flag"),
        Rule(term="self harm", category="self-harm", action="flag"),
        Rule(term="rape", category="sexual violence", action="flag"),
        Rule(term="terrorist", category="violent extremism", action="flag"),
        Rule(term="genocide", category="violent extremism", action="flag"),
        Rule(term="mass shooting", category="graphic violence", action="flag"),
    ],
    block_threshold=DEFAULT_BLOCK_THRESHOLD,
)


class ContentBlockedError(Exception):
    """The request's text matched a blocking rule. ``categories`` is what the user is told."""

    def __init__(self, categories: list[str]) -> None:
        self.categories = categories
        super().__init__(
            f"This request wasn't generated because parts of it look like {' / '.join(categories)} content, "
            "which our content policy doesn't allow. If we misread your intent, try rephrasing the prompt, "
            "style or lyrics."
        )


@dataclass
class ScreeningResult:
    blocked: bool
    categories: list[str]

    @property
    def flags(self) -> list[str]:
        return [] if self.blocked else self.categories


def _normalise(text: str) -> str:
    """Lowercase, fold accents ("heíl" -> "heil") and treat punctuation as spaces ("child-porn")."""
    folded = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return " ".join(re.sub(r"[\W_]+", " ", folded.lower()).split())


def _phrase(term: str) -> re.Pattern[str]:
    return re.compile(rf"(?<!\w){re.escape(_normalise(term))}(?!\w)")


def match(rules: ScreeningRules, texts: Iterable[str | None]) -> ScreeningResult:
    """Screen ``texts`` against ``rules``. Pure — no storage, so it is cheap to test."""
    # ponytail: regexes compiled per call; cache per rule set if rule lists grow to thousands.
    text = " | ".join(_normalise(t) for t in texts if t)
    for allowed in rules.allow_terms:
        if _normalise(allowed):
            text = _phrase(allowed).sub(" ", text)

    blocked: list[str] = []
    flagged: list[str] = []
    for rule in rules.rules:
        hits = blocked if rule.action == "block" else flagged
        if rule.category not in hits and _phrase(rule.term).search(text):
            hits.append(rule.category)

    if blocked:
        return ScreeningResult(blocked=True, categories=blocked)
    escalate = rules.block_threshold > 0 and len(flagged) >= rules.block_threshold
    return ScreeningResult(blocked=escalate, categories=flagged)


async def get_rules() -> ScreeningRules:
    doc = await ScreeningRulesDocument.find_one(ScreeningRulesDocument.key == "global")
    return DEFAULT_RULES if doc is None else ScreeningRules.model_validate(doc.model_dump())


async def save_rules(rules: ScreeningRules) -> ScreeningRules:
    await ScreeningRulesDocument.get_pymongo_collection().update_one(
        {"key": "global"}, {"$set": rules.model_dump()}, upsert=True
    )
    return rules


async def enforce(*texts: str | None) -> list[str]:
    """Raise :class:`ContentBlockedError` for blocked text; return the flag categories otherwise.

    Call before charging credits, so a blocked request never costs anything.
    """
    result = match(await get_rules(), texts)
    if result.blocked:
        raise ContentBlockedError(result.categories)
    return result.flags
