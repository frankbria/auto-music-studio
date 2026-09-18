#pragma once

#include "PlatformClient.h"

namespace acemusic
{
namespace Platform
{

/**
    The plugin's sign-in to the platform, kept alive past the access token's lifetime (#445).

    The musician pastes a **plugin token** — a refresh token from Settings on the web app.
    Access tokens (15 minutes) are only ever held in memory: `run` sends the current one,
    and on a 401 swaps the refresh token for a new pair and retries the call once.

    Refresh tokens are single-use, so the rotated one replaces the old on disk straight
    away. It lives in its own 0600 file rather than the settings file because every plugin
    instance in a DAW keeps its own copy of the settings in memory, and any of them saving
    would write back a spent token. Before refreshing, the file is re-read, which is how an
    instance picks up a rotation another one made.

    Thread-safe: the panel and a voiced generation call it from different workers.
*/
class Session
{
public:
    /** @param tokenFile  where the refresh token persists; `juce::File()` keeps it in memory */
    explicit Session (juce::File tokenFile);

    juce::String getRefreshToken() const;

    /** A newly pasted plugin token. Persisted, and the old access token is dropped. Empty
        signs out. */
    void setRefreshToken (const juce::String& token);

    /** Runs `call` with the current access token, refreshing and retrying once on a 401.

        Blocking — worker threads only. A token the platform still refuses after that is
        reported as such, never retried again.

        @param shouldCancel  checked before a refresh starts: a closing plugin must not
                             spend a single-use token, nor hold the process-wide refresh
                             lock across a network call */
    Result run (const juce::String& baseUrl,
                const std::function<Result (const juce::String& accessToken)>& call,
                const std::function<bool()>& shouldCancel = nullptr);

private:
    /** Swaps the refresh token for a new pair, unless another caller already replaced
        `rejectedAccess`. @returns an error to show, or empty on success. */
    juce::String renew (const juce::String& baseUrl, const juce::String& rejectedAccess,
                        const std::function<bool()>& shouldCancel);

    void persist (const juce::String& token);

    const juce::File tokenFile;
    mutable juce::CriticalSection lock;
    juce::String accessToken, refreshToken;
};

} // namespace Platform
} // namespace acemusic
