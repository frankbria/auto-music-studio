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
    @param timeoutMs     what exactly this bounds is platform-dependent — see
                         defaultProbeTimeoutMs
*/
ProbeResult probeAceStepServer (const juce::String& baseUrl,
                                const juce::String& apiKey,
                                std::function<bool()> shouldCancel = nullptr,
                                int timeoutMs = 2000);

/** Timeout for a probe.

    Sized against plugin teardown. juce::ThreadPool gives in-flight work ~5s before
    abandoning it (see BackgroundTaskQueue), and a probe running on a worker cannot
    interrupt its own blocking call, so this has to leave room.

    **What it bounds differs by platform**, which is worth knowing before tuning it:
    - Linux/BSD (JUCE's own socket implementation, JUCE_USE_CURL=0): a *connect*
      timeout, re-applied as the poll timeout before each read. A stalled server
      therefore costs up to 2x this value.
    - macOS: becomes NSURLRequest.timeoutInterval — an inactivity timeout across the
      whole request, not just the connect.
    - Windows: WinHTTP connect/send/receive timeouts.

    So the honest worst case is ~2x on Linux (~4s at 2s, inside the ~5s budget; 3s
    would have overrun it) and ~1x elsewhere.

    **Not a hard bound on Linux.** The read path polls with this timeout but then
    calls `recv(..., MSG_WAITALL)`, which blocks until the requested bytes arrive. A
    server that sends a partial body and then neither sends nor closes can still
    block a worker indefinitely. Bounding that needs a watchdog thread calling
    `WebInputStream::cancel()`; US-23.3 has to build that anyway for long-running
    generation requests, so it is tracked (#317) rather than half-solved here. */
constexpr int defaultProbeTimeoutMs = 2000;

/** Splits the model names out of a `/v1/stats` body. Exposed for testing the
    envelope handling without a server. */
juce::StringArray parseModelNames (const juce::String& responseBody);

} // namespace acemusic
