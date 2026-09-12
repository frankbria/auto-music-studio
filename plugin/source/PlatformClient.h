#pragma once

#include <juce_core/juce_core.h>

#include <functional>

#ifndef ACEMUSIC_HAS_TLS
 #define ACEMUSIC_HAS_TLS 1
#endif

namespace acemusic
{

/**
    Talks to the Auto Music Studio **platform** API — the web app — as opposed to the
    local ACE-Step server that `AceStepClient` drives.

    Two different servers with two different jobs, so two clients: ACE-Step generates
    audio on `localhost`, the platform stores the musician's workspaces and clips
    remotely. Nothing here shares state with the generation path, which is what keeps
    a platform outage from touching local generation (US-24.5 AC 5).

    **Blocking.** Every call here goes on a BackgroundTaskQueue worker, never the audio
    or message thread.

    **TLS.** The platform is a remote HTTPS host. macOS (NSURLSession) and Windows
    (WinHTTP) do TLS natively; Linux needs libcurl, and a build without it cannot reach
    an `https://` URL at all. `hasTlsSupport()` reports that up front so the panel can
    explain itself instead of failing a request with an unactionable socket error.
*/
namespace Platform
{
    /** Whether this build can reach an `https://` URL. False only on a Linux build
        made without libcurl development headers. */
    constexpr bool hasTlsSupport() noexcept                   { return ACEMUSIC_HAS_TLS != 0; }

    /** One workspace, as the platform lists them. */
    struct Workspace
    {
        juce::String id;
        juce::String name;
    };

    /** One clip, with the metadata the plugin shows and uses. */
    struct Clip
    {
        juce::String id;
        juce::String title;
        juce::String format;
        double duration = 0.0;
        int bpm = 0;
        juce::String key;
        juce::StringArray styleTags;
        juce::String createdAt;
    };

    /** One custom voice model the signed-in musician owns (#396). */
    struct VoiceModel
    {
        juce::String id;
        juce::String name;
        /** "queued" | "training" | "ready" | "failed". Only "ready" can generate. */
        juce::String status;
    };

    /** What every call reports back. `ok` false always carries an `errorMessage` the
        panel can show verbatim. */
    struct Result
    {
        bool ok = false;
        juce::String errorMessage;

        /** True when the caller asked to stop. Not a failure — the UI shows nothing. */
        bool cancelled = false;

        juce::Array<Workspace> workspaces;
        juce::Array<Clip> clips;
        juce::Array<VoiceModel> voiceModels;

        /** The job a platform-routed generation created, and what it is doing. */
        juce::String jobId;
        bool jobComplete = false;
        bool jobFailed = false;
        juce::StringArray clipIds;

        /** Total matches, for paging. */
        int total = 0;

        /** The clip a push created, or an import wrote to. */
        juce::String clipId;
        juce::File file;
    };

    //==============================================================================
    /** Why `baseUrl` cannot be used, or empty when it can. Catches the `https://` on a
        no-TLS build case before any request is made. */
    juce::String findUrlProblem (const juce::String& baseUrl);

    /** `GET /api/v1/workspaces`. */
    Result listWorkspaces (const juce::String& baseUrl,
                           const juce::String& apiKey,
                           std::function<bool()> shouldCancel = nullptr,
                           int timeoutMs = 10000);

    /** `GET /api/v1/clips`, optionally filtered.
        @param search  matched against title and style tags by the server
        @param workspaceId  empty for "every workspace" */
    Result listClips (const juce::String& baseUrl,
                      const juce::String& apiKey,
                      const juce::String& workspaceId,
                      const juce::String& search,
                      int page = 1,
                      int perPage = 20,
                      std::function<bool()> shouldCancel = nullptr,
                      int timeoutMs = 10000);

    /** `GET /api/v1/clips/{id}/audio`, written to `destination`. */
    Result downloadClip (const juce::String& baseUrl,
                         const juce::String& apiKey,
                         const juce::String& clipId,
                         const juce::File& destination,
                         std::function<bool()> shouldCancel = nullptr,
                         int timeoutMs = 60000);

    /** `POST /api/v1/clips/upload` — pushes a local clip into a workspace. */
    Result uploadClip (const juce::String& baseUrl,
                       const juce::String& apiKey,
                       const juce::String& workspaceId,
                       const juce::File& audio,
                       const juce::String& title,
                       int bpm,
                       const juce::String& key,
                       double durationSeconds,
                       std::function<bool()> shouldCancel = nullptr,
                       int timeoutMs = 120000);

    /** The voice models this musician owns, newest first (#396).

        Every status is returned; call `readyVoiceModels` to get the ones that can
        actually generate. Keeping them separate means the panel can say "still training"
        rather than silently showing a shorter list than the web app does. */
    Result listVoiceModels (const juce::String& baseUrl,
                            const juce::String& apiKey,
                            std::function<bool()> shouldCancel = nullptr,
                            int timeoutMs = 10000);

    /** Just the models whose adapter has finished training. */
    juce::Array<VoiceModel> readyVoiceModels (const juce::Array<VoiceModel>&);

    /** Start a generation on the platform: `POST /api/v1/generate`, returns `jobId`.

        `payloadJson` comes from `GenerationRequest::toPlatformPayloadJson()` — the
        endpoint forbids unknown keys, so the ACE-Step body will not do.

        Failures carry the platform's own message where it sends one (a Pro-only refusal,
        a credit shortfall), because "API key rejected by the server" would misdescribe
        both. */
    Result submitGeneration (const juce::String& baseUrl,
                             const juce::String& apiKey,
                             const juce::String& payloadJson,
                             std::function<bool()> shouldCancel = nullptr,
                             int timeoutMs = 30000);

    /** Poll `GET /api/v1/jobs/{id}/status`.

        `ok` means the poll itself worked; `jobFailed` with `errorMessage` is the job
        failing, which is a different thing and must not be reported as a network error.
        Completed jobs carry `clipIds` — preferred over the response's `audio_urls`, which
        for local-disk storage can be filesystem paths rather than anything fetchable. */
    Result getJobStatus (const juce::String& baseUrl,
                         const juce::String& apiKey,
                         const juce::String& jobId,
                         std::function<bool()> shouldCancel = nullptr,
                         int timeoutMs = 10000);

    /** Settings keys, so the panel and the settings file agree on one spelling. */
    constexpr const char* urlKey = "platformUrl";
    constexpr const char* apiKeyKey = "platformApiKey";
    constexpr const char* workspaceKey = "platformWorkspaceId";
    constexpr const char* voiceModelKey = "platformVoiceModelId";

    /** Where the platform lives by default. */
    constexpr const char* defaultUrl = "https://api.acemusic.ai";
}

} // namespace acemusic
