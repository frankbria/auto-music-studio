"""Applying a trained voice to a generation (US-25.4).

ACE-Step's LoRA is *handler state*, not a per-task parameter: ``/release_task`` has no
``lora_path`` field, so whichever adapter is loaded conditions **every** task the host
runs. Two consequences, and this module exists for both:

* A voice job and an ordinary job running at the same time against one host share that
  adapter, so the ordinary job comes back singing in someone else's voice. Every local
  generation therefore goes through :func:`active_voice`, which holds a single lock for
  the whole submit-and-poll.
* Loading a 43MB adapter that is already loaded is wasted work, so the state of the host
  is tracked and ``/v1/lora/{load,unload}`` is only called when it has to change.

A fresh process assumes the host is on its base model, so a deployment that never uses a
custom voice never talks to ``/v1/lora`` at all. Once anything *is* loaded the tracking is
exact, and any failed call marks the state unknown so the next generation re-states what it
wants — a stale belief here means audio in the wrong voice, which is worse than a redundant
HTTP call.

ponytail: the tracked state is per-process and covers one ACE-Step host. Several workers
against one host would each believe their own answer — move the state into Mongo, or to
named adapters (``/v1/lora/load`` takes ``adapter_name``), if that day comes. If a worker
is killed mid-voice-job its adapter stays loaded until the next generation that wants
something else, which self-corrects; read ``/v1/lora/status`` on startup only if that turns
out to matter.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx

from ..models import Job
from ..services import voice_models as voice_service
from .common import JobProcessingError

logger = logging.getLogger(__name__)

#: How long to wait on a LoRA load. An adapter is tens of megabytes off local disk;
#: generous, but not unbounded, so a wedged host fails the job instead of the worker.
LORA_TIMEOUT_S = 120.0


class VoiceAdapterError(Exception):
    """The requested voice could not be made active on the ACE-Step host."""


class _AdapterState:
    """The adapter this process believes is loaded on one ACE-Step host.

    Generations wanting the adapter that is already loaded run concurrently, exactly as
    they did before voices existed. Only a *change* is exclusive: it waits for the
    in-flight generations to drain, swaps the adapter, and lets everyone in again.
    """

    def __init__(self) -> None:
        self._cond = asyncio.Condition()
        #: Adapter path believed loaded, or None for the base model.
        self._loaded: str | None = None
        #: Whether ``_loaded`` can be trusted. Starts True on the base-model assumption
        #: above; a failed call clears it so the next generation re-states its adapter.
        self._synced = True
        #: Generations currently running on ``_loaded``.
        self._users = 0
        #: Generations queued to change it. New arrivals queue behind them even when the
        #: current adapter suits, so a steady stream of one voice cannot starve another.
        self._switchers = 0
        #: Bumped on every adapter change. A waiter may only skip its own switch if a
        #: change happened *after it started waiting* — without that test a new arrival
        #: whose adapter is already loaded would walk straight past a queued switcher,
        #: and under steady traffic that switcher would never see the host go quiet.
        self._epoch = 0

    @asynccontextmanager
    async def hold(self, base_url: str, weights_path: str | None) -> AsyncIterator[None]:
        """Hold the host with ``weights_path`` (or the base model) as its active adapter."""
        await self._acquire(base_url, weights_path)
        try:
            yield
        finally:
            await self._release()

    def _matches(self, weights_path: str | None) -> bool:
        return self._synced and self._loaded == weights_path

    async def _acquire(self, base_url: str, weights_path: str | None) -> None:
        async with self._cond:
            if self._matches(weights_path) and self._switchers == 0:
                self._users += 1
                return

            entered_at = self._epoch
            self._switchers += 1
            try:
                # Either someone else swaps to what we want while we wait — in which case
                # we ride in behind them — or the host goes quiet and we swap it ourselves.
                while not ((self._epoch != entered_at and self._matches(weights_path)) or self._users == 0):
                    await self._cond.wait()
                if not self._matches(weights_path):
                    await self._apply(base_url, weights_path)
            finally:
                self._switchers -= 1

            self._users += 1
            # Anyone queued for the adapter just loaded can come in behind us.
            self._cond.notify_all()

    async def _release(self) -> None:
        async with self._cond:
            self._users -= 1
            if self._users == 0:
                self._cond.notify_all()

    async def _apply(self, base_url: str, weights_path: str | None) -> None:
        # Pessimistic before the call, not after: a request that times out may still
        # have landed, so the state is only trustworthy once a response comes back.
        self._synced = False
        try:
            async with httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=LORA_TIMEOUT_S) as client:
                if weights_path is None:
                    response = await client.post("/v1/lora/unload")
                else:
                    response = await client.post("/v1/lora/load", json={"lora_path": weights_path})
                response.raise_for_status()
        except httpx.HTTPError as exc:
            # Waiters are blocked on us; wake them so one of them can retry rather than
            # hang behind a switch that never happened.
            self._cond.notify_all()
            raise VoiceAdapterError(f"Could not activate voice adapter on ACE-Step: {exc}") from exc

        self._loaded = weights_path
        self._synced = True
        self._epoch += 1
        logger.info("ACE-Step voice adapter set to %s", weights_path or "the base model")


_STATE = _AdapterState()


@asynccontextmanager
async def active_voice(base_url: str | None, weights_path: str | None) -> AsyncIterator[None]:
    """Run the body with ``weights_path`` as the ACE-Step host's active adapter.

    ``base_url`` is None for backends with no LoRA support (RunPod); a voice asked for
    there is an error rather than a silently ignored parameter.
    """
    if base_url is None:
        if weights_path is not None:
            raise VoiceAdapterError("Custom voices are only available on local compute.")
        yield
        return

    async with _STATE.hold(base_url, weights_path):
        yield


async def resolve_weights(job: Job) -> str | None:
    """The adapter path a queued job asked for, or None if it named no voice.

    Re-checked here rather than trusted from enqueue time: a voice can be deleted
    between queueing and running, and generating in the base voice instead — silently
    — is not what was paid for.
    """
    voice_model_id = (job.input_params or {}).get("voice_model_id")

    if not voice_model_id:
        return None

    try:
        return await voice_service.weights_for(str(voice_model_id), str(job.user_id))
    except (voice_service.VoiceModelNotFoundError, voice_service.VoiceModelNotReadyError) as exc:
        raise JobProcessingError(str(exc)) from exc
