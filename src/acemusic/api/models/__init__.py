"""Beanie ODM document models for the platform's core collections (US-8.2).

``ALL_MODELS`` is the registration list passed to ``init_beanie``.
"""

from .clip import Clip
from .job import Job, JobStatus
from .user import User
from .workspace import Workspace

ALL_MODELS = [User, Workspace, Clip, Job]

__all__ = ["User", "Workspace", "Clip", "Job", "JobStatus", "ALL_MODELS"]
