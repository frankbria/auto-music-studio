"""Experimental features on /labs, and their rollout (US-28.5, #342).

A feature is on for a user when an admin has made it available to them (to everyone, or to them by name) and the
user has switched it on for themselves. Every write is a targeted update: users and flags are edited concurrently by
admins and the people they belong to.
"""

from dataclasses import dataclass
from typing import Literal

from beanie import PydanticObjectId
from fastapi import HTTPException, status

from ..models import FeatureFlagSetting, User
from . import moderation

Stage = Literal["alpha", "beta"]


@dataclass(frozen=True)
class Experiment:
    key: str
    name: str
    description: str
    stage: Stage


CATALOG: tuple[Experiment, ...] = (
    Experiment(
        "real_time_generation",
        "Real-time generation",
        "Hear a song take shape while it is being generated.",
        "alpha",
    ),
    Experiment(
        "collaborative_workspaces",
        "Collaborative workspaces",
        "Share a workspace and make songs in it together.",
        "alpha",
    ),
    Experiment("ai_arrangement", "AI arrangement", "Let the model arrange a song's sections for you.", "beta"),
    Experiment("style_transfer", "Style transfer", "Re-render a song in the style of another.", "beta"),
)
_BY_KEY = {experiment.key: experiment for experiment in CATALOG}


def _experiment(key: str) -> Experiment:
    if key not in _BY_KEY:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such experimental feature.")
    return _BY_KEY[key]


async def _settings() -> dict[str, FeatureFlagSetting]:
    return {flag.key: flag for flag in await FeatureFlagSetting.find_all().to_list()}


def _available(setting: FeatureFlagSetting | None, user_id: PydanticObjectId) -> bool:
    return bool(setting and (setting.enabled_for_everyone or user_id in setting.user_ids))


async def labs_for(user: User) -> list[dict]:
    """Every experiment as this user sees it: whether they may use it, and whether they have switched it on."""
    settings = await _settings()
    return [
        {
            "key": experiment.key,
            "name": experiment.name,
            "description": experiment.description,
            "stage": experiment.stage,
            "available": (available := _available(settings.get(experiment.key), user.id)),
            "enabled": available and experiment.key in user.labs_opt_ins,
        }
        for experiment in CATALOG
    ]


async def is_enabled(user: User, key: str) -> bool:
    """Whether a feature is on for this user: available to them, and switched on by them."""
    return key in user.labs_opt_ins and _available(await FeatureFlagSetting.find_one({"key": key}), user.id)


async def set_opt_in(user: User, key: str, enabled: bool) -> None:
    """Switch an experiment on or off for this user; 403 when it isn't available to them."""
    _experiment(key)
    if enabled and not _available(await FeatureFlagSetting.find_one({"key": key}), user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This feature isn't available to you yet.")
    update = {"$addToSet": {"labs_opt_ins": key}} if enabled else {"$pull": {"labs_opt_ins": key}}
    await User.find({"_id": user.id}).update(update)


async def admin_overview() -> list[dict]:
    """Every experiment's rollout, with the email of each user granted it."""
    settings = await _settings()
    granted_ids = {uid for setting in settings.values() for uid in setting.user_ids}
    emails = {u.id: u.email for u in await User.find({"_id": {"$in": list(granted_ids)}}).to_list()}
    return [
        {
            "key": experiment.key,
            "name": experiment.name,
            "stage": experiment.stage,
            "enabled_for_everyone": bool(setting and setting.enabled_for_everyone),
            "users": [{"id": str(uid), "email": emails.get(uid)} for uid in (setting.user_ids if setting else [])],
        }
        for experiment in CATALOG
        for setting in [settings.get(experiment.key)]
    ]


async def _upsert(key: str, update: dict) -> None:
    await FeatureFlagSetting.get_pymongo_collection().update_one({"key": key}, update, upsert=True)


async def set_everyone(actor_id: str, key: str, enabled: bool) -> None:
    """Roll an experiment out to everyone, or back to only the users granted it."""
    _experiment(key)
    await _upsert(key, {"$set": {"enabled_for_everyone": enabled}})
    await moderation.log_action(actor_id, "feature_flag_everyone", "feature_flag", key, None, {"enabled": enabled})


async def set_user_grant(actor_id: str, key: str, email: str, granted: bool) -> None:
    """Grant an experiment to one user, by email, or take it back; 404 for an unknown email."""
    _experiment(key)
    user = await User.find_one(User.email == email.strip())
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No user has that email address.")
    update = {"$addToSet": {"user_ids": user.id}} if granted else {"$pull": {"user_ids": user.id}}
    await _upsert(key, update)
    action = "feature_flag_granted" if granted else "feature_flag_revoked"
    await moderation.log_action(actor_id, action, "feature_flag", key, None, {"user_id": str(user.id), "email": email})
