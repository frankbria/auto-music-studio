"""Beanie ODM document models for the platform's core collections (US-8.2).

``ALL_MODELS`` is the registration list passed to ``init_beanie``.
"""

from .batch_job import BatchClipEntry, BatchJob
from .clip import Clip
from .credit_transaction import CreditTransaction
from .job import Job, JobStatus
from .preset import PRESET_PARAM_FIELDS, Preset
from .refresh_token import RefreshToken
from .user import User
from .workspace import Workspace

ALL_MODELS = [User, Workspace, Clip, Job, RefreshToken, Preset, CreditTransaction, BatchJob]

__all__ = [
    "User",
    "Workspace",
    "Clip",
    "CreditTransaction",
    "Job",
    "JobStatus",
    "BatchJob",
    "BatchClipEntry",
    "RefreshToken",
    "Preset",
    "PRESET_PARAM_FIELDS",
    "ALL_MODELS",
]
