"""Who may use each experimental feature (US-28.5, #342).

The features themselves are listed in ``services/feature_flags.CATALOG``; this records an admin's rollout of one:
everyone, or only the users granted it. A user then switches it on for themselves on /labs (``User.labs_opt_ins``).
"""

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import ASCENDING, IndexModel


class FeatureFlagSetting(Document):
    key: str
    enabled_for_everyone: bool = False
    user_ids: list[PydanticObjectId] = Field(default_factory=list)

    class Settings:
        name = "feature_flags"
        indexes = [IndexModel([("key", ASCENDING)], unique=True)]
