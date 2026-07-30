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
    @param timeoutMs     connection timeout, deliberately below the plugin's
                         shutdown budget (see defaultTimeoutMs)
*/
ProbeResult probeAceStepServer (const juce::String& baseUrl,
                                const juce::String& apiKey,
                                std::function<bool()> shouldCancel = nullptr,
                                int timeoutMs = 3000);

/** Connection timeout for a probe.

    juce::ThreadPool gives in-flight work ~5s before abandoning it (see
    BackgroundTaskQueue), and a probe cannot be interrupted mid-connect from the
    thread it runs on. Keeping the timeout below that budget means the worst case is
    a bounded delay on plugin teardown rather than an abandoned thread. */
constexpr int defaultProbeTimeoutMs = 3000;

/** Splits the model names out of a `/v1/stats` body. Exposed for testing the
    envelope handling without a server. */
juce::StringArray parseModelNames (const juce::String& responseBody);

} // namespace acemusic
