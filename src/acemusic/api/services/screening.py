"""Automated content screening for generation requests (US-27.1) and the text clips display (#531).

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

from ..models import Clip
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

    def __init__(self, categories: list[str], *, saving: bool = False) -> None:
        self.categories = categories
        outcome, fix = (
            ("This wasn't saved", "rephrasing it")
            if saving
            else ("This request wasn't generated", "rephrasing the prompt, style or lyrics")
        )
        super().__init__(
            f"{outcome} because parts of it look like {' / '.join(categories)} content, "
            f"which our content policy doesn't allow. If we misread your intent, try {fix}."
        )


@dataclass
class ScreeningResult:
    blocked: bool
    categories: list[str]

    @property
    def flags(self) -> list[str]:
        return [] if self.blocked else self.categories


#: Letters that render like Latin ones, applied before lowercasing because the capitals differ
#: ("Н" is H, "н" isn't). NFKD already folds fullwidth and mathematical letters. Past the Cyrillic and
#: Greek basics, the rows are confusables.txt (Unicode 18) entries that map onto one Latin letter (#561).
#: ponytail: a subset of confusables.txt for the scripts evasion has used; load the whole table only with a
#: false-positive pass over every script it folds. Icelandic "þ" is left out: it is a letter there ("þorn" isn't "porn").
_HOMOGLYPHS = str.maketrans(
    "АВЕКМНОРСТУХІЈЅҺԚԜӀ"
    "аеорсухіјѕһԁӏԛԝ"
    "ΑΒΕΖΗΙΚΜΝΟΡΤΥΧ"
    "αεικνορτυχ"
    "ϲϹϜϳͿϺσϱϸᴦγϒ"
    "քցհւյոռօՕգզՏսՍա"
    "ᎪᏏᏴꮯᏟᏧᎠᎬᏀᏳᏂᎻꭵᎥᎫᏦᏞᎷᏢꮁᎡᏒꮪᏕᏚᎢꮩᏙꮃꮤᎳᏔᎩᎽꮓᏃ"
    "ɑꭤƄꞴᴄꬲꬵꞙƒʄẝꞘɡᶃƍıɪɩȷꞲꞮꟾƖꞁǀᴏᴑꬽƿꭇꭈƦɌꜱƽꞟᴜꭎꭒʋᴠɯꟺᴡꞳɣᶌʏỿꭚᴢⱬⱫ",
    "ABEKMHOPCTYXIJSHQWl"
    "aeopcyxijshdlqw"
    "ABEZHIKMNOPTYX"
    "aeikvoptux"
    "cCFjJMoppryY"
    "fghijnnoOqqSuUw"
    "AbBcCdDEGGhHiiJKLMPrRRsSSTvVwwWWYYzZ"
    "aabBcefffffFgggiiijJllllloooprrRRssuuuuuvwwwXyyyyyzzZ",
)

#: Leet stand-ins per letter. Expanded on the rule side, so "1" can be both "i" and "l".
_LEET = {"a": "4@", "b": "8", "e": "3", "g": "69", "i": "1", "l": "1", "o": "0", "s": "5$", "t": "7", "z": "2"}


#: Stands in for a zero-width character. A rule may find it inside a word ("sie\u200bg") or between
#: two ("sieg\u200bheil"), so one reading of the text covers both, however they are mixed.
_INVISIBLE = "\x00"

#: Hangul fillers render blank but are letters (category Lo). NFKD maps U+3164 and U+FFA0 onto U+1160.
_BLANK_LETTERS = "\u115f\u1160"


def _is_invisible(c: str) -> bool:
    """For a character of NFKD text that ``combining()`` reports as 0."""
    return unicodedata.category(c) in ("Cf", "Mn") or c in _BLANK_LETTERS


def has_invisible(term: str) -> bool:
    """Whether a rule term hides a zero-width character, which would silently join the words around it."""
    return any(_is_invisible(c) for c in unicodedata.normalize("NFKD", term) if not unicodedata.combining(c))


def _normalise(text: str, *, keep: str = "") -> str:
    """Lowercase, fold accents ("heíl"), homoglyphs ("hеil") and punctuation ("child-porn") to plain words.

    Zero-width characters (format characters such as a zero-width space, the non-combining marks
    NFKD leaves, like variation selectors, and blank filler letters) become ``_INVISIBLE``.
    ``keep`` names punctuation that survives, for leet matching ("$ieg").
    """
    # Homoglyphs fold before NFKD as well as after, since NFKD turns lunate sigma "Ϲ" into an unmapped "Σ".
    folded = "".join(
        _INVISIBLE if _is_invisible(c) else c
        for c in unicodedata.normalize("NFKD", text.translate(_HOMOGLYPHS))
        if not unicodedata.combining(c)
    )
    return " ".join(
        re.sub(rf"[^\w{re.escape(keep + _INVISIBLE)}]+|_", " ", folded.translate(_HOMOGLYPHS).lower()).split()
    )


def _words(term: str) -> list[str]:
    return _normalise(term).replace(_INVISIBLE, "").split()


def _letter(c: str, leet: bool) -> str:
    return f"[{re.escape(c + _LEET[c])}]" if leet and c in _LEET else re.escape(c)


def _phrase(term: str, leet: bool) -> re.Pattern[str]:
    """Whole-word pattern for ``term``: invisibles may sit between its letters, and a space may be any run of
    spaces and invisibles, plus "@"/"$" under leet ("sieg$heil"), since those are letters only by position."""
    gap = re.escape(_INVISIBLE) + "*"
    separator = f"[ {re.escape(_INVISIBLE + ('@$' if leet else ''))}]+"
    body = separator.join(gap.join(_letter(c, leet) for c in word) for word in _words(term))
    return re.compile(rf"(?<!\w){body}(?!\w)")


_LETTER = re.compile(r"[^\W\d_]")


def _found(term: str, leet: bool, text: str) -> bool:
    """Under leet, a term with letters needs a letter in the match too: "to" must not match "70" (#561)."""
    needs_letter = leet and _LETTER.search(term)
    return any(not needs_letter or _LETTER.search(m.group()) for m in _phrase(term, leet).finditer(text))


def match(rules: ScreeningRules, texts: Iterable[str | None]) -> ScreeningResult:
    """Screen ``texts`` against ``rules``. Pure — no storage, so it is cheap to test."""
    # ponytail: regexes compiled per call; cache per rule set if rule lists grow to thousands.
    leet = rules.fold_leetspeak
    text = " | ".join(_normalise(t, keep="@$" if leet else "") for t in texts if t)
    for allowed in rules.allow_terms:
        if _words(allowed):
            # Replaced by the field joiner, which no pattern spans: a space would let "white [house] power" join up.
            text = _phrase(allowed, leet).sub(" | ", text)

    blocked: list[str] = []
    flagged: list[str] = []
    for rule in rules.rules:
        hits = blocked if rule.action == "block" else flagged
        if rule.category not in hits and _words(rule.term) and _found(rule.term, leet, text):
            hits.append(rule.category)

    if blocked:
        return ScreeningResult(blocked=True, categories=blocked)
    escalate = rules.block_threshold > 0 and len(flagged) >= rules.block_threshold
    return ScreeningResult(blocked=escalate, categories=flagged)


#: Every free-text param any iterative mode carries (US-10.3 request models).
ITERATIVE_TEXT_PARAMS = ("prompt", "style", "style_override", "lyrics", "lyrics_override", "vocal_style")


def clip_texts(*clips: Clip) -> list[str | None]:
    """A clip's text as generation uses it: title, lyrics, and the tags *joined*.

    Workers prompt with ``", ".join(style_tags)``, so tags are screened as that one
    string — separately, ``["sieg", "heil"]`` would never match the phrase it forms.
    """
    return [text for clip in clips for text in (clip.title, ", ".join(clip.style_tags), clip.lyrics)]


async def get_rules() -> ScreeningRules:
    doc = await ScreeningRulesDocument.find_one(ScreeningRulesDocument.key == "global")
    return DEFAULT_RULES if doc is None else ScreeningRules.model_validate(doc.model_dump())


async def save_rules(rules: ScreeningRules, fields: set[str] | None = None) -> ScreeningRules:
    """Write ``fields`` (all by default) atomically; the rest only seed a first save, so PATCHes don't race."""
    values = rules.model_dump()
    sent = values.keys() if fields is None else fields
    await ScreeningRulesDocument.get_pymongo_collection().update_one(
        {"key": "global"},
        {"$set": {k: values[k] for k in sent}, "$setOnInsert": {k: v for k, v in values.items() if k not in sent}},
        upsert=True,
    )
    return rules


async def enforce(*texts: str | None, saving: bool = False) -> list[str]:
    """Raise :class:`ContentBlockedError` for blocked text; return the flag categories otherwise.

    Call before charging credits, so a blocked request never costs anything. ``saving``
    words the refusal for metadata a user stores (a title, a voice name) rather than generates.
    """
    if not any(texts):
        return []
    result = match(await get_rules(), texts)
    if result.blocked:
        raise ContentBlockedError(result.categories, saving=saving)
    return result.flags
