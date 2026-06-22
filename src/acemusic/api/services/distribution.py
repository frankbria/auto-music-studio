"""Guided distribution prep service (US-13.5).

LANDR, DistroKid, and TuneCore have no public submission API, so the platform
prepares a release *package* to each target's requirements and hands the user a
checklist plus a downloadable bundle to submit manually.

A release is a metadata wrapper around a clip: the audio lives at
``clip.file_path`` and the cover art at ``clip.artwork_path`` (US-13.1), so
validation and bundling read the source clip rather than the release. Target
rules are plain data in :data:`TARGET_CONFIGS` so adding a platform is a dict
entry, not new code.
"""

from __future__ import annotations

import asyncio
import io
import json
import tempfile
import zipfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from pydantic import BaseModel

from ...constants import ARTWORK_MIN_RESOLUTION, VALID_IMAGE_FORMATS
from ...image_processing import ImageValidationError, validate_image
from ...storage import get_storage_backend
from ...utils import make_slug
from ..models import Release
from . import clips as clip_service

# Lossless masters only — all three targets reject lossy uploads for the master.
_ACCEPTED_AUDIO_FORMATS: frozenset[str] = frozenset({"wav", "flac"})

# Release metadata required for a compliant submission (all enforced at create,
# but isrc/upc are clearable via PATCH so they're re-checked here).
_REQUIRED_METADATA: tuple[str, ...] = ("title", "artist", "genre", "release_date")


class DistributionTarget(str, Enum):
    """Supported manual-distribution platforms."""

    LANDR = "landr"
    DISTROKID = "distrokid"
    TUNECORE = "tunecore"


@dataclass(frozen=True)
class TargetRequirements:
    """A target platform's package requirements and submission instructions."""

    label: str
    instructions: str
    accepted_audio_formats: frozenset[str] = _ACCEPTED_AUDIO_FORMATS
    accepted_artwork_formats: frozenset[str] = VALID_IMAGE_FORMATS
    min_artwork_resolution: int = ARTWORK_MIN_RESOLUTION
    required_metadata: tuple[str, ...] = _REQUIRED_METADATA


def _instructions(label: str, portal: str) -> str:
    return (
        f"Submitting to {label}:\n"
        f"1. Download this bundle and unzip it.\n"
        f"2. Sign in to {portal} and start a new release.\n"
        f"3. Upload audio.* as the track and cover.* as the artwork.\n"
        f"4. Copy the title, artist, genre, release date, ISRC, and UPC from "
        f"metadata.json into the release form.\n"
        f"5. Submit on {label}, then confirm here to mark the release submitted."
    )


TARGET_CONFIGS: dict[DistributionTarget, TargetRequirements] = {
    DistributionTarget.LANDR: TargetRequirements(
        label="LANDR",
        instructions=_instructions("LANDR", "landr.com/distribution"),
    ),
    DistributionTarget.DISTROKID: TargetRequirements(
        label="DistroKid",
        instructions=_instructions("DistroKid", "distrokid.com"),
    ),
    DistributionTarget.TUNECORE: TargetRequirements(
        label="TuneCore",
        instructions=_instructions("TuneCore", "tunecore.com"),
    ),
}


def instructions_for(target: DistributionTarget) -> str:
    """Return the submission instructions for ``target``."""
    return TARGET_CONFIGS[target].instructions


class ChecklistItem(BaseModel):
    """One pass/fail line in a preparation checklist."""

    item: str
    passed: bool
    message: str


@dataclass
class _Validation:
    """Validation result plus the bytes downloaded to produce it (reused by the
    bundle so a passing prepare downloads each asset once)."""

    checklist: list[ChecklistItem]
    audio: bytes | None = None
    audio_format: str | None = None
    artwork: bytes | None = None
    artwork_format: str | None = None


def is_release_ready(checklist: list[ChecklistItem]) -> bool:
    """True only if every checklist item passed."""
    return all(c.passed for c in checklist)


async def _validate(release: Release, target: DistributionTarget) -> _Validation:
    reqs = TARGET_CONFIGS[target]
    checklist: list[ChecklistItem] = []
    result = _Validation(checklist=checklist)

    clip = await clip_service.find_owned_clip(str(release.clip_id), str(release.user_id))
    storage = get_storage_backend()

    # Audio: the clip holds the master; download it both to confirm the object
    # exists and to reuse for the bundle when everything passes.
    if clip is None:
        checklist.append(
            ChecklistItem(item="Audio file present", passed=False, message="Source clip is no longer available.")
        )
    else:
        try:
            result.audio = await asyncio.to_thread(storage.download, clip.file_path)
        except FileNotFoundError:
            checklist.append(
                ChecklistItem(item="Audio file present", passed=False, message="Audio file is missing from storage.")
            )
        else:
            result.audio_format = (clip.format or "").lower()
            checklist.append(ChecklistItem(item="Audio file present", passed=True, message="Audio file is available."))
        fmt = (clip.format or "").lower()
        if fmt in reqs.accepted_audio_formats:
            checklist.append(ChecklistItem(item="Audio format", passed=True, message=f"{fmt.upper()} is accepted."))
        else:
            accepted = ", ".join(sorted(f.upper() for f in reqs.accepted_audio_formats))
            checklist.append(
                ChecklistItem(
                    item="Audio format",
                    passed=False,
                    message=f"Format {fmt or 'unknown'!r} is not accepted; use one of: {accepted}.",
                )
            )

    # Cover art: presence + resolution, reusing the artwork validator.
    art_path = clip.artwork_path if clip is not None else None
    if not art_path:
        checklist.append(ChecklistItem(item="Cover art", passed=False, message="Cover art has not been added."))
    else:
        try:
            result.artwork = await asyncio.to_thread(storage.download, art_path)
            fmt, width, height = validate_image(result.artwork)
        except (FileNotFoundError, ImageValidationError) as exc:
            checklist.append(
                ChecklistItem(item="Cover art", passed=False, message=f"Cover art could not be read: {exc}")
            )
        else:
            result.artwork_format = fmt
            ok = (
                fmt in reqs.accepted_artwork_formats
                and width >= reqs.min_artwork_resolution
                and height >= reqs.min_artwork_resolution
            )
            min_res = reqs.min_artwork_resolution
            checklist.append(
                ChecklistItem(
                    item="Cover art",
                    passed=ok,
                    message=(
                        f"{width}x{height} {fmt.upper()} cover art."
                        if ok
                        else f"Cover art is {width}x{height} {fmt.upper()}; "
                        f"need >= {min_res}x{min_res} in {', '.join(sorted(reqs.accepted_artwork_formats))}."
                    ),
                )
            )

    # Metadata completeness.
    missing = [f for f in reqs.required_metadata if not getattr(release, f, None)]
    checklist.append(
        ChecklistItem(
            item="Required metadata",
            passed=not missing,
            message="All required metadata is present." if not missing else f"Missing metadata: {', '.join(missing)}.",
        )
    )

    # Identifiers (US-13.4) — clearable via PATCH, so re-check.
    checklist.append(
        ChecklistItem(item="ISRC assigned", passed=bool(release.isrc), message=release.isrc or "No ISRC assigned.")
    )
    checklist.append(
        ChecklistItem(item="UPC assigned", passed=bool(release.upc), message=release.upc or "No UPC assigned.")
    )
    return result


async def validate_release(release: Release, target: DistributionTarget) -> list[ChecklistItem]:
    """Validate ``release`` against ``target``'s requirements, returning a checklist."""
    return (await _validate(release, target)).checklist


def _metadata_json(release: Release) -> str:
    fields = (
        "title",
        "artist",
        "genre",
        "release_date",
        "album_name",
        "description",
        "isrc",
        "upc",
        "copyright",
        "is_explicit",
        "language",
        "credits",
    )
    payload: dict[str, object] = {"release_id": str(release.id)}
    for f in fields:
        value = getattr(release, f, None)
        payload[f] = value.isoformat() if hasattr(value, "isoformat") else value
    return json.dumps(payload, indent=2)


def _bundle_key(release: Release, target: DistributionTarget) -> str:
    return f"{release.user_id}/releases/{release.id}/bundles/{target.value}.zip"


def _build_zip(validation: _Validation, release: Release, target: DistributionTarget) -> bytes:
    """Assemble the target bundle as zip bytes (audio + cover + metadata + README)."""
    slug = make_slug(release.title) or f"release-{release.id}"
    root = f"{slug}_for_{target.value}"
    audio_ext = validation.audio_format or "wav"
    art_ext = "jpg" if validation.artwork_format == "jpeg" else (validation.artwork_format or "png")

    with tempfile.TemporaryDirectory() as tmp:
        tree = Path(tmp) / root
        tree.mkdir(parents=True)
        if validation.audio is not None:
            (tree / f"audio.{audio_ext}").write_bytes(validation.audio)
        if validation.artwork is not None:
            (tree / f"cover.{art_ext}").write_bytes(validation.artwork)
        (tree / "metadata.json").write_text(_metadata_json(release))
        (tree / "README.txt").write_text(instructions_for(target))

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(tree.rglob("*")):
                if path.is_file():
                    zf.write(path, f"{root}/{path.relative_to(tree).as_posix()}")
        return buffer.getvalue()


async def prepare_release(release: Release, target: DistributionTarget) -> tuple[list[ChecklistItem], str | None]:
    """Validate ``release`` for ``target`` and, if it passes, build and upload the bundle.

    Returns ``(checklist, bundle_url)`` where ``bundle_url`` is ``None`` when any
    check fails. The bundle reuses the assets downloaded during validation, so a
    passing prepare downloads each source object exactly once.
    """
    validation = await _validate(release, target)
    if not is_release_ready(validation.checklist):
        return validation.checklist, None

    # _build_zip does synchronous tempfile/zip I/O — keep it off the event loop.
    data = await asyncio.to_thread(_build_zip, validation, release, target)
    key = _bundle_key(release, target)
    storage = get_storage_backend()
    # upload() overwrites the key, so re-preparing a target replaces its bundle
    # in place — no separate delete (which would leave a window with no bundle if
    # the upload then failed).
    await asyncio.to_thread(storage.upload, key, data)
    return validation.checklist, storage.get_url(key)
