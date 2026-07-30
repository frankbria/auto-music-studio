#include "AceStepClient.h"

namespace acemusic
{

juce::StringArray parseModelNames (const juce::String& responseBody)
{
    juce::StringArray names;

    const auto parsed = juce::JSON::parse (responseBody);

    // The envelope is {"data": {...}}, but the payload is sometimes returned bare.
    auto payload = parsed.getProperty ("data", juce::var());
    if (payload.isVoid() || ! payload.getDynamicObject())
        payload = parsed;

    auto* object = payload.getDynamicObject();
    if (object == nullptr)
        return names;

    if (auto* models = object->getProperty ("models").getArray())
    {
        for (const auto& model : *models)
        {
            // Entries are {"name": "..."}; tolerate a bare string too.
            const auto name = model.isString() ? model.toString()
                                               : model.getProperty ("name", juce::var()).toString();

            if (name.isNotEmpty())
                names.add (name);
        }
    }

    return names;
}

ProbeResult probeAceStepServer (const juce::String& baseUrl,
                                const juce::String& apiKey,
                                std::function<bool()> shouldCancel,
                                int timeoutMs)
{
    ProbeResult result;

    const auto stopRequested = [&shouldCancel] { return shouldCancel != nullptr && shouldCancel(); };

    const auto trimmed = baseUrl.trim();
    if (trimmed.isEmpty())
    {
        result.errorMessage = "No server URL set";
        return result;
    }

    // The key is pasted into a text field, so a trailing newline is a routine
    // accident — trim it rather than punishing the user with a 401. A control
    // character *inside* the key is not an accident we can safely fix: interpolating
    // it into the header would let it terminate the line and forge another, so fail
    // closed with something diagnosable instead of silently mangling the key.
    const auto key = apiKey.trim();

    for (const auto c : key)
    {
        if (c < ' ' || c == 127)
        {
            result.errorMessage = "API key contains invalid characters";
            return result;
        }
    }

    const juce::URL url (trimmed.trimCharactersAtEnd ("/") + "/v1/stats");
    const auto scheme = url.getScheme().toLowerCase();

    // Check the scheme explicitly rather than just "non-empty": a typo'd ftp:// or
    // file:// would otherwise get as far as the socket and come back as a vague
    // connection error.
    if (! url.isWellFormed() || (scheme != "http" && scheme != "https"))
    {
        result.errorMessage = "Server URL must start with http:// or https://";
        return result;
    }

    if (stopRequested())
    {
        result.cancelled = true;
        return result;
    }

    juce::WebInputStream stream (url, false);
    stream.withConnectionTimeout (timeoutMs);

    if (key.isNotEmpty())
        stream.withExtraHeaders ("Authorization: Bearer " + key);

    if (! stream.connect (nullptr))
    {
        if (stopRequested())
        {
            result.cancelled = true;
            return result;
        }

        // JUCE reports connect failure and DNS/refusal the same way, so this covers
        // "nothing listening", "wrong port", and "unknown host" alike. That is what
        // the user needs to know either way.
        result.errorMessage = "Server unreachable";
        return result;
    }

    const auto status = stream.getStatusCode();

    if (status == 401 || status == 403)
    {
        result.errorMessage = apiKey.isEmpty() ? "Server requires an API key"
                                               : "API key rejected by the server";
        return result;
    }

    if (status < 200 || status >= 300)
    {
        result.errorMessage = "Server returned HTTP " + juce::String (status);
        return result;
    }

    if (stopRequested())
    {
        result.cancelled = true;
        stream.cancel();
        return result;
    }

    const auto body = stream.readEntireStreamAsString();

    result.models = parseModelNames (body);

    if (result.models.isEmpty())
    {
        // Reached a server that answered 2xx but told us nothing usable — a
        // different service on the port, or ACE-Step with no models loaded.
        result.errorMessage = "Connected, but the server reported no models";
        return result;
    }

    result.ok = true;
    return result;
}

} // namespace acemusic
