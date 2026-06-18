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
import time

from acemusic.mastering_protocol import MasteringError, MasteringOutput, MasteringService

logger = logging.getLogger(__name__)

# Canonical fallback order: Dolby.io (primary, US-12.2) -> LANDR (B2B, US-12.3)
# -> Bakuage (cost-effective open API, US-12.3). The chain honours this order for
# fallback candidates regardless of which service was requested.
DEFAULT_FALLBACK_ORDER: tuple[str, ...] = ("dolby", "landr", "bakuage")

# Overall deadline for one mastering run's full fallback chain. The processor's
# stale-job threshold defaults to poll_timeout (600s) + 300s = 900s; bounding the
# whole chain to 600s keeps a multi-backend run comfortably inside that window so
# a restart-driven re-queue cannot duplicate a still-live job (codex review P2).
DEFAULT_TOTAL_TIMEOUT_S: float = 600.0


class ServiceNotConfiguredError(Exception):
    """Raised when an explicitly requested mastering service has no configured client.

    Distinct from :class:`~acemusic.mastering_protocol.MasteringError` so the
    handler can refund the credits charged at enqueue (no mastering work was
    performed) and report a clear "not configured" failure rather than retrying.
    """


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
        total_timeout: float = DEFAULT_TOTAL_TIMEOUT_S,
    ) -> MasteringOutput:
        """Master ``audio_bytes`` via the requested service, falling back on failure.

        Raises :class:`ServiceNotConfiguredError` if the requested service has no
        configured client (no silent substitution). Raises the last
        :class:`~acemusic.mastering_protocol.MasteringError` if every service in
        the chain fails (or the overall deadline elapsed before another attempt).

        ``total_timeout`` bounds the *whole* fallback chain: each backend is given
        the time remaining on the deadline as its poll budget, so a chain of
        hanging backends cannot run many minutes past the processor's stale-job
        window (which would let a second processor re-queue and duplicate the
        job). The default fits within the processor's default stale threshold.
        """
        if not self.is_service_available(requested_service):
            raise ServiceNotConfiguredError(
                f"Mastering service {requested_service!r} is not configured. "
                f"Available: {', '.join(self.available_services) or 'none'}."
            )

        chain = self._fallback_chain(requested_service)
        deadline = time.monotonic() + total_timeout
        last_error: MasteringError | None = None
        for index, svc in enumerate(chain):
            if index == 0:
                # The requested service always gets a full attempt with the whole
                # budget; only *fallback* attempts are gated by remaining time.
                remaining_budget = total_timeout
            else:
                remaining_budget = deadline - time.monotonic()
                if remaining_budget <= 0:
                    # Deadline exhausted by earlier attempts: stop starting
                    # fallbacks so the chain cannot run far past the processor's
                    # stale-job window (which would duplicate the job on restart).
                    logger.error(
                        "Mastering fallback deadline (%.0fs) elapsed before trying %s; no further attempts",
                        total_timeout,
                        svc,
                    )
                    break
            client = self._clients[svc]
            try:
                output = client.master(
                    audio_bytes, filename, profile, target_lufs, output_format, timeout=remaining_budget
                )
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
        # Every configured service failed (or the deadline elapsed); propagate.
        if last_error is None:
            # Deadline elapsed before any backend raised an error.
            raise MasteringError(
                f"Mastering fallback deadline ({total_timeout:.0f}s) elapsed before any backend completed"
            )
        raise last_error
