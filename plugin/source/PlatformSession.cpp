#include "PlatformSession.h"
#include "ConnectionSettings.h"

namespace acemusic
{
namespace Platform
{

namespace
{
    constexpr const char* tokenRejected = "Plugin token rejected - create a new one in Settings on the web app";
    constexpr const char* tokenMissing = "The platform needs a plugin token - create one in Settings on the web app";

    /** `renew`'s answer when it was told to stop. Never shown: `run` reports a cancel. */
    constexpr const char* stopped = "stopped";

    /** Serialises every refresh in the process, not just this session's: two plugin
        instances share one token file, and a single-use token refreshed twice signs one
        of them out. Held across the network call on purpose. */
    juce::CriticalSection& refreshLock()
    {
        static juce::CriticalSection instance;
        return instance;
    }
}

Session::Session (juce::File file)
    : tokenFile (std::move (file))
{
    if (tokenFile != juce::File() && tokenFile.existsAsFile())
        refreshToken = tokenFile.loadFileAsString().trim();
}

juce::String Session::getRefreshToken() const
{
    const juce::ScopedLock sl (lock);
    return refreshToken;
}

void Session::setRefreshToken (const juce::String& token)
{
    const juce::ScopedLock refreshing (refreshLock());
    {
        const juce::ScopedLock sl (lock);
        refreshToken = token.trim();
        accessToken.clear();
    }
    persist (token.trim());
}

Result Session::run (const juce::String& baseUrl,
                     const std::function<Result (const juce::String&)>& call,
                     const std::function<bool()>& shouldCancel)
{
    const auto stopping = [&] { return shouldCancel != nullptr && shouldCancel(); };

    const auto access = [this] { const juce::ScopedLock sl (lock); return accessToken; }();

    // No access token yet (a fresh start) goes out bare: the 401 it earns is what
    // triggers the first refresh, so there is one path rather than two.
    auto result = call (access);

    if (! result.unauthorised)
        return result;

    if (getRefreshToken().isEmpty())
    {
        result.errorMessage = tokenMissing;
        return result;
    }

    if (const auto error = renew (baseUrl, access, stopping); error.isNotEmpty())
    {
        Result failed;
        failed.cancelled = (error == stopped);
        failed.errorMessage = failed.cancelled ? juce::String() : error;
        return failed;
    }

    result = call ([this] { const juce::ScopedLock sl (lock); return accessToken; }());

    // Refused with a token minted a moment ago: nothing more to try.
    if (result.unauthorised)
        result.errorMessage = tokenRejected;

    return result;
}

juce::String Session::renew (const juce::String& baseUrl, const juce::String& rejectedAccess,
                             const std::function<bool()>& shouldCancel)
{
    const juce::ScopedLock refreshing (refreshLock());
    juce::String token;

    // It may have waited out another instance's refresh, and been asked to stop meanwhile.
    if (shouldCancel())
        return stopped;

    {
        const juce::ScopedLock sl (lock);

        // Another call hit the same 401 and already refreshed while this one waited.
        if (accessToken.isNotEmpty() && accessToken != rejectedAccess)
            return {};

        // Another plugin instance may have rotated it since this one read the file.
        if (tokenFile.existsAsFile())
            if (const auto onDisk = tokenFile.loadFileAsString().trim(); onDisk.isNotEmpty())
                refreshToken = onDisk;

        token = refreshToken;
    }

    const auto refreshed = refreshTokens (baseUrl, token, shouldCancel);

    if (refreshed.cancelled)
        return stopped;

    if (! refreshed.ok)
        return refreshed.unauthorised ? juce::String (tokenRejected) : refreshed.errorMessage;

    {
        const juce::ScopedLock sl (lock);
        accessToken = refreshed.accessToken;
        refreshToken = refreshed.refreshToken;
    }

    persist (refreshed.refreshToken);
    return {};
}

void Session::persist (const juce::String& token)
{
    if (tokenFile == juce::File())
        return;

    if (token.isEmpty())
    {
        tokenFile.deleteFile();
        return;
    }

    // Directory to 0700 before the write, file to 0600 after: the write goes through the
    // umask, same as the settings file (see ConnectionSettings::restrictPermissions).
    ConnectionSettings::restrictPermissions (tokenFile);
    tokenFile.replaceWithText (token);
    ConnectionSettings::restrictPermissions (tokenFile);
}

} // namespace Platform
} // namespace acemusic
