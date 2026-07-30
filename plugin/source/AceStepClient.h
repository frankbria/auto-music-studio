#pragma once

#include <juce_core/juce_core.h>

#include <functional>

namespace acemusic
{

/** Outcome of a single availability probe. */
struct ProbeResult
{
    bool ok = false;

    /** Model names the server reports, in the order it listed them. */
    juce::StringArray models;

    /** User-facing reason the probe failed. Empty when ok. */
    juce::String errorMessage;

    /** True when the probe returned early because the caller asked it to stop.
        Distinct from a failure — the UI should not show an error for it. */
    bool cancelled = false;
};

/**
    Probes an ACE-Step server and reads back its model list.

    The endpoint is `GET /v1/stats`, matching what the Python side already treats as
    the availability probe (`AceStepClient.get_stats`, `compute_status`) — ACE-Step
    has no `/health`. The response envelope is
    `{"data": {"models": [{"name": …}], …}}`, and `data` may be absent, in which
    case the body itself is the payload.

    **Blocking.** Call this only from a BackgroundTaskQueue worker, never from the
    audio or message thread.

    @param baseUrl       e.g. "http://localhost:8001"; a trailing slash is fine
    @param apiKey        sent as `Authorization: Bearer …`; omitted when empty
    @param shouldCancel  polled around the blocking steps; may be null
    @param timeoutMs     applies to the connect *and* to each read (see
                         defaultProbeTimeoutMs)
*/
ProbeResult probeAceStepServer (const juce::String& baseUrl,
                                const juce::String& apiKey,
                                std::function<bool()> shouldCancel = nullptr,
                                int timeoutMs = 2000);

/** Timeout for a probe, applied to the connect and to each socket read.

    Sized against plugin teardown. juce::ThreadPool gives in-flight work ~5s before
    abandoning it (see BackgroundTaskQueue), and a probe running on a worker cannot
    interrupt its own blocking socket call. A stalled server costs one connect
    timeout plus one read timeout, so 2s keeps the normal worst case (~4s) inside
    that budget where 3s (~6s) would have overrun it.

    **Not a hard bound.** JUCE's read path polls with this timeout but then calls
    `recv(..., MSG_WAITALL)`, which blocks until the requested bytes arrive. A server
    that sends a partial body and then neither sends nor closes can still block a
    worker indefinitely. Bounding that needs a watchdog thread to call
    `WebInputStream::cancel()`; US-23.3 has to solve it properly for long-running
    generation requests, so it is tracked rather than half-solved here. */
constexpr int defaultProbeTimeoutMs = 2000;

/** Splits the model names out of a `/v1/stats` body. Exposed for testing the
    envelope handling without a server. */
juce::StringArray parseModelNames (const juce::String& responseBody);

} // namespace acemusic
