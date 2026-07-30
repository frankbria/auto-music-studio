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

//==============================================================================
/** Outcome of submitting a generation task. */
struct SubmitResult
{
    bool ok = false;
    juce::String taskId;
    juce::String errorMessage;
    bool cancelled = false;
};

/** Where a submitted task has got to. */
struct TaskStatus
{
    enum class State
    {
        pending,    ///< queued or running (the server reports 0 for both)
        completed,
        failed
    };

    bool ok = false;                ///< the *query* succeeded; see state for the task
    State state = State::pending;
    juce::StringArray audioUrls;    ///< absolute URLs, only when completed
    juce::String errorMessage;      ///< query failure, or the task's own error
    bool cancelled = false;
};

/** Submits a generation task.

    `POST /release_task`; the task id comes back as `data.task_id` (or `data.id`).
    Blocking — call from a BackgroundTaskQueue worker only. */
SubmitResult submitGeneration (const juce::String& baseUrl,
                               const juce::String& apiKey,
                               const juce::String& payloadJson,
                               std::function<bool()> shouldCancel = nullptr,
                               int timeoutMs = defaultProbeTimeoutMs);

/** Polls one task.

    `POST /query_result` with `{"task_id_list":[id]}`. The server reports status as
    an integer (0 queued/running, 1 succeeded, 2 failed) and hands back `result` as a
    **JSON string** containing `[{"file": "/v1/audio?path=..."}]`, which is why this
    returns parsed URLs rather than the raw body. Blocking. */
TaskStatus queryTask (const juce::String& baseUrl,
                      const juce::String& apiKey,
                      const juce::String& taskId,
                      std::function<bool()> shouldCancel = nullptr,
                      int timeoutMs = defaultProbeTimeoutMs);

/** Downloads one generated clip to `destination`.

    @returns an error message, or empty on success. Blocking. */
juce::String downloadAudio (const juce::String& audioUrl,
                            const juce::String& apiKey,
                            const juce::File& destination,
                            std::function<bool()> shouldCancel = nullptr,
                            int timeoutMs = 30000);

/** Parses a `/query_result` body. Exposed so the envelope handling — including the
    JSON-string `result` field — can be tested without a server. */
TaskStatus parseTaskStatus (const juce::String& responseBody, const juce::String& baseUrl);

} // namespace acemusic
