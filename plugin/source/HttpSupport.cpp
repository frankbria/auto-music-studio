#include "HttpSupport.h"

namespace acemusic
{
namespace Http
{

/** Trims a pasted key and rejects one that could forge a header line.

    A trailing newline off a copy-paste is a routine accident worth fixing
    quietly. A control character *inside* the key is not: interpolating it into
    the Authorization header would terminate the line and forge another, so fail
    closed with something diagnosable rather than silently mangling it.

    @param error  set to the reason when the key is unusable
    @returns      the sanitised key */
juce::String sanitiseKey (const juce::String& apiKey, juce::String& error)
{
    const auto key = apiKey.trim();

    for (const auto c : key)
    {
        if (c < ' ' || c == 127)
        {
            error = "API key contains invalid characters";
            return {};
        }
    }

    return key;
}

Endpoint prepareEndpoint (const juce::String& baseUrl,
                          const juce::String& apiKey,
                          const juce::String& path)
{
    Endpoint endpoint;

    const auto trimmed = baseUrl.trim();
    if (trimmed.isEmpty())
    {
        endpoint.error = "No server URL set";
        return endpoint;
    }

    endpoint.key = sanitiseKey (apiKey, endpoint.error);

    if (endpoint.error.isNotEmpty())
        return endpoint;

    endpoint.url = juce::URL (trimmed.trimCharactersAtEnd ("/") + path);
    const auto scheme = endpoint.url.getScheme().toLowerCase();

    // Check the scheme explicitly rather than just "non-empty": a typo'd ftp:// or
    // file:// would otherwise get as far as the socket and come back as a vague
    // connection error.
    if (! endpoint.url.isWellFormed() || (scheme != "http" && scheme != "https"))
        endpoint.error = "Server URL must start with http:// or https://";

    return endpoint;
}

/** Applies the shared request setup. */
void configure (juce::WebInputStream& stream, const Endpoint& endpoint, int timeoutMs)
{
    stream.withConnectionTimeout (timeoutMs);

    if (endpoint.key.isNotEmpty())
        stream.withExtraHeaders ("Authorization: Bearer " + endpoint.key);
}

/** Turns a non-2xx status into the message the user should see, or empty if the
    status is fine. */
juce::String describeStatus (int status, const juce::String& key)
{
    // Status 0 means no HTTP response was received at all. The socket backend reports
    // that by failing connect(), but curl's connect() succeeds and leaves the status at
    // 0 — so once JUCE_USE_CURL was turned on for US-24.5, an unreachable server started
    // reporting "Server returned HTTP 0" instead of something a user can act on.
    if (status <= 0)
        return "Server unreachable";

    if (status == 401 || status == 403)
    {
        // `key` is the *sanitised* value: a whitespace-only entry sends no header
        // at all, so "rejected" would be wrong — nothing was offered to reject.
        return key.isEmpty() ? "Server requires an API key"
                             : "API key rejected by the server";
    }

    if (status < 200 || status >= 300)
        return "Server returned HTTP " + juce::String (status);

    return {};
}

/** The payload the server wraps everything in: {"data": ..., "code": ...}.
    `data` is sometimes absent, in which case the body itself is the payload. */
juce::var unwrapEnvelope (const juce::var& parsed)
{
    auto payload = parsed.getProperty ("data", juce::var());

    if (payload.isVoid() || (! payload.getDynamicObject() && payload.getArray() == nullptr))
        return parsed;

    return payload;
}

} // namespace Http
} // namespace acemusic
