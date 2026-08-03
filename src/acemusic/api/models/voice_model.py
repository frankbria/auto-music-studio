"""Voice model document (US-25.1).

A custom voice trained from the musician's own reference recordings, via
ACE-Step's LoRA fine-tuning. The document tracks the model through training and
holds the exported weights key once it is ready.

Private by construction: every read is owner-scoped, which is what US-25.3's
"other users cannot see or access another user's voice models" rests on.
"""

from datetime import datetime
from enum import Enum

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import ASCENDING, IndexModel

from .common import utcnow

#: Bounds from the story: enough references to characterise a voice, few enough
#: that training stays minutes rather than hours.
MIN_REFERENCE_FILES = 2
MAX_REFERENCE_FILES = 10

#: Below this the reference carries too little detail for the model to learn a
#: voice from, and training would burn credits to produce something unusable.
MIN_SAMPLE_RATE_HZ = 16000

#: A reference shorter than this is not a voice, it is a syllable.
MIN_REFERENCE_SECONDS = 1.0

#: Guard against a single enormous upload; ten of these is the real bound.
MAX_REFERENCE_BYTES = 50 * 1024 * 1024


class VoiceModelStatus(str, Enum):
    """Mirrors the job lifecycle, with ``ready`` as the terminal success state.

    Deliberately distinct from ``JobStatus``: a voice model outlives the job that
    produced it, and "completed job" and "usable voice" are not the same claim.
    """

    QUEUED = "queued"
    TRAINING = "training"
    READY = "ready"
    FAILED = "failed"


class VoiceModel(Document):
    """One custom voice, and the training run that produced it."""

    user_id: PydanticObjectId
    name: str
    description: str | None = None

    status: VoiceModelStatus = VoiceModelStatus.QUEUED

    #: Storage keys of the uploaded references, in upload order.
    reference_paths: list[str] = Field(default_factory=list)

    #: Storage key of the exported LoRA weights. None until training succeeds —
    #: which is the difference between a model that exists and one that is usable.
    weights_path: str | None = None

    #: The training job, so status can be followed without a second lookup table.
    job_id: PydanticObjectId | None = None

    #: Why training failed, shown to the owner. None unless status is ``failed``.
    error: str | None = None

    #: Credits taken for this training run, so a refund cannot guess the amount
    #: and a price change cannot retroactively alter what someone gets back.
    credits_charged: float = 0.0

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    @property
    def reference_count(self) -> int:
        return len(self.reference_paths)

    @property
    def is_usable(self) -> bool:
        """Ready *and* actually holding weights — the check a generation should make."""
        return self.status is VoiceModelStatus.READY and bool(self.weights_path)

    class Settings:
        name = "voice_models"
        indexes = [
            # Every listing is "this user's models, newest first" (US-25.3).
            IndexModel([("user_id", ASCENDING), ("created_at", ASCENDING)]),
            IndexModel([("job_id", ASCENDING)]),
        ]
