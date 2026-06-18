"""Mastering service orchestrator with automatic fallback (US-12.3).

The orchestrator sits between the mastering job handler and the three mastering
backends (Dolby.io, LANDR, Bakuage). It selects the requested backend via the
``service`` parameter and, when that backend fails, retries the next *configured*
backend in the canonical order — so a Dolby.io outage transparently falls back to
LANDR, then to Bakuage, without the handler knowing which backend ran.

Fallback policy (see ``tasks/todo.md`` for the rationale):

- An explicitly requested service that is **not configured** raises
  :class:`ServiceNotConfiguredError` rather than silently substituting another
  backend — the handler refunds the credits charged at enqueue and reports a
  clear failure. (Request validation happens upstream, so the user's intent is
  honored: only *available* services are chosen.)
- A configured service that **fails at runtime** triggers a fallback to the next
  configured service in :data:`DEFAULT_FALLBACK_ORDER`. Any
  :class:`~acemusic.mastering_protocol.MasteringError` qualifies: since the
  request is already validated by the time a backend is called, a backend error
  is a service-side failure worth retrying elsewhere.
- Each service is tried at most once. If every service in the chain fails, the
  last error propagates. The result is tagged with the service that actually
  succeeded, so a fallback run is distinguishable from the requested one.
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from acemusic.mastering_protocol import MasteringError, MasteringOutput, MasteringService

logger = logging.getLogger(__name__)

# Canonical fallback order: Dolby.io (primary, US-12.2) -> LANDR (B2B, US-12.3)
# -> Bakuage (cost-effective open API, US-12.3). The chain honours this order for
# fallback candidates regardless of which service was requested.
DEFAULT_FALLBACK_ORDER: tuple[str, ...] = ("dolby", "landr", "bakuage")


class ServiceNotConfiguredError(Exception):
    """Raised when an explicitly requested mastering service has no configured client.

    Distinct from :class:`~acemusic.mastering_protocol.MasteringError` so the
    handler can refund the credits charged at enqueue (no mastering work was
    performed) and report a clear "not configured" failure rather than retrying.
    """


# A narrow callable type for the master entrypoint, so the orchestrator doesn't
# import each concrete client. ``MasteringService`` (the runtime-checkable
# Protocol) is the public contract; this alias documents the dispatch surface.
@runtime_checkable
class _MasterCallable(Protocol):
    service: str

    def master(
        self,
        audio_bytes: bytes,
        filename: str,
        profile: str,
        target_lufs: float,
        output_format: str,
    ) -> MasteringOutput: ...


class MasteringOrchestrator:
    """Selects a mastering backend and falls back across configured services.

    Constructed with the set of configured clients keyed by their canonical
    service name (only services whose credentials are present appear in the
    mapping). :meth:`master_with_fallback` runs the requested service first, then
    retries the remaining configured services in :data:`DEFAULT_FALLBACK_ORDER`.
    """

    def __init__(self, clients: dict[str, MasteringService]) -> None:
        # Copy to avoid mutation by callers; only retain services with a client.
        self._clients: dict[str, MasteringService] = {
            svc: client for svc, client in clients.items() if client is not None
        }

    @property
    def available_services(self) -> tuple[str, ...]:
        """The configured service names, in canonical fallback order."""
        return tuple(svc for svc in DEFAULT_FALLBACK_ORDER if svc in self._clients)

    def is_service_available(self, service: str) -> bool:
        """Return True if ``service`` has a configured client."""
        return service in self._clients

    def get_client(self, service: str) -> MasteringService:
        """Return the configured client for ``service`` or raise if unconfigured."""
        if service not in self._clients:
            raise ServiceNotConfiguredError(
                f"Mastering service {service!r} is not configured. "
                f"Available: {', '.join(self.available_services) or 'none'}."
            )
        return self._clients[service]

    def _fallback_chain(self, requested_service: str) -> list[str]:
        """Build the try-order: requested service first, then configured others."""
        chain = [requested_service] if requested_service in self._clients else []
        for svc in DEFAULT_FALLBACK_ORDER:
            if svc != requested_service and svc in self._clients:
                chain.append(svc)
        return chain

    def master_with_fallback(
        self,
        audio_bytes: bytes,
        filename: str,
        profile: str,
        target_lufs: float,
        output_format: str,
        *,
        requested_service: str,
    ) -> MasteringOutput:
        """Master ``audio_bytes`` via the requested service, falling back on failure.

        Raises :class:`ServiceNotConfiguredError` if the requested service has no
        configured client (no silent substitution). Raises the last
        :class:`~acemusic.mastering_protocol.MasteringError` if every service in
        the chain fails.
        """
        if not self.is_service_available(requested_service):
            raise ServiceNotConfiguredError(
                f"Mastering service {requested_service!r} is not configured. "
                f"Available: {', '.join(self.available_services) or 'none'}."
            )

        chain = self._fallback_chain(requested_service)
        last_error: MasteringError | None = None
        for index, svc in enumerate(chain):
            client = self._clients[svc]
            try:
                output = client.master(audio_bytes, filename, profile, target_lufs, output_format)
            except MasteringError as exc:
                last_error = exc
                remaining = len(chain) - index - 1
                if remaining > 0:
                    logger.warning(
                        "Mastering service %s failed (%s); falling back (%d service(s) left)",
                        svc,
                        exc,
                        remaining,
                    )
                else:
                    logger.error("Mastering service %s failed (%s); no configured fallback remains", svc, exc)
                continue
            if svc != requested_service:
                logger.info("Mastering fell back from %s to %s", requested_service, svc)
            return output
        # Every configured service failed; propagate the last backend error.
        assert last_error is not None  # pragma: no cover - chain is non-empty here
        raise last_error
