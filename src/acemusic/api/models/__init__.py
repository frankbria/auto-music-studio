"""Beanie ODM document models for the platform's core collections (US-8.2).

``ALL_MODELS`` is the registration list passed to ``init_beanie``.
"""

from .artwork import ArtworkOption
from .batch_job import BatchClipEntry, BatchJob
from .billing_event import BillingEvent
from .clip import Clip
from .clip_report import ClipReport, ReportCategory
from .counter import Counter
from .credit_transaction import CreditTransaction
from .distribution import DistributionStatus, VisibilityState
from .job import Job, JobStatus
from .notification_event import NotificationEvent
from .preset import PRESET_PARAM_FIELDS, Preset
from .queue import PlaybackQueue, RepeatMode
from .refresh_token import RefreshToken
from .release import Release, ReleaseStatus
from .screening import ScreeningRulesDocument
from .soundcloud_connection import SoundCloudConnection
from .user import OAuthIdentity, User
from .video import Video
from .voice_model import VoiceModel, VoiceModelStatus
from .workspace import Workspace

ALL_MODELS = [
    User,
    Workspace,
    Clip,
    Job,
    RefreshToken,
    Preset,
    BillingEvent,
    CreditTransaction,
    BatchJob,
    ArtworkOption,
    SoundCloudConnection,
    Release,
    NotificationEvent,
    Counter,
    PlaybackQueue,
    Video,
    VoiceModel,
    ScreeningRulesDocument,
    ClipReport,
]

__all__ = [
    "VoiceModel",
    "VoiceModelStatus",
    "OAuthIdentity",
    "User",
    "Workspace",
    "Clip",
    "ClipReport",
    "ReportCategory",
    "ArtworkOption",
    "BillingEvent",
    "CreditTransaction",
    "Job",
    "JobStatus",
    "BatchJob",
    "BatchClipEntry",
    "RefreshToken",
    "Preset",
    "PRESET_PARAM_FIELDS",
    "SoundCloudConnection",
    "Release",
    "ReleaseStatus",
    "DistributionStatus",
    "VisibilityState",
    "NotificationEvent",
    "Counter",
    "PlaybackQueue",
    "RepeatMode",
    "Video",
    "ScreeningRulesDocument",
    "ALL_MODELS",
]
