"""Async job dispatch for the platform API.

The generation endpoint (US-9.1) persists a queued :class:`~acemusic.api.models.job.Job`
and then hands it off via :func:`dispatch_job`. This module owns that hand-off
seam. Today it records the enqueue; the worker-queue integration (publishing to
the task queue, worker pickup, status transitions ``queued -> processing -> …``)
is delivered by US-9.2, which extends this function without changing its contract.
"""

import logging

logger = logging.getLogger(__name__)


async def dispatch_job(job_id: str) -> None:
    """Hand a persisted, queued job off for asynchronous processing.

    The job already exists in MongoDB with ``status=queued`` before this is
    called; dispatch is the signal that it is ready for a worker to pick up. The
    actual queue publish is implemented in US-9.2.
    """
    logger.info("Job %s enqueued for processing", job_id)
