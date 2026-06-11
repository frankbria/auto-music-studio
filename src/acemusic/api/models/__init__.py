"""Beanie ODM document models for the platform's core collections (US-8.2).

``ALL_MODELS`` is the registration list passed to ``init_beanie``.
"""

from .clip import Clip
from .job import Job, JobStatus
from .preset import PRESET_PARAM_FIELDS, Preset
from .refresh_token import RefreshToken
from .user import User
from .workspace import Workspace

ALL_MODELS = [User, Workspace, Clip, Job, RefreshToken, Preset]

__all__ = [
    "User",
    "Workspace",
    "Clip",
    "Job",
    "JobStatus",
    "RefreshToken",
    "Preset",
    "PRESET_PARAM_FIELDS",
    "ALL_MODELS",
]
