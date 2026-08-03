#pragma once

#include <juce_core/juce_core.h>

namespace acemusic
{

/**
    The request plumbing shared by every HTTP client in the plugin.

    Extracted at its second caller (`AceStepClient`, `PlatformClient`) rather than
    earlier, and specifically because `sanitiseKey` is security-relevant: a control
    character interpolated into an `Authorization` header terminates the line and forges
    another. That is not a check to re-derive per client and get subtly wrong the second
    time.
*/
namespace Http
{
    /** A validated endpoint: where to send, and the sanitised key to send with it. */
    struct Endpoint
    {
        juce::URL url;
        juce::String key;

        /** Non-empty means "reject without touching the network". */
        juce::String error;
    };

    /** Trims a pasted key and rejects one that could forge a header line.

        A trailing newline off a copy-paste is a routine accident, fixed quietly. A
        control character *inside* the key is not: it would terminate the Authorization
        header and let another be injected, so that fails closed with a diagnosable
        message.

        @param error  set to the reason when the key is unusable
        @returns      the sanitised key */
    juce::String sanitiseKey (const juce::String& apiKey, juce::String& error);

    /** Builds and validates `baseUrl + path`, rejecting a scheme that is not http(s)
        explicitly — a typo'd `ftp://` would otherwise reach the socket and come back as
        a vague connection error. */
    Endpoint prepareEndpoint (const juce::String& baseUrl,
                              const juce::String& apiKey,
                              const juce::String& path);

    /** Applies the shared request setup: timeout, and the bearer header when there is
        a key to send. */
    void configure (juce::WebInputStream&, const Endpoint&, int timeoutMs);

    /** Turns a non-2xx status into the message the user should see, or empty when the
        status is fine.

        @param key  the *sanitised* key: a blank one sends no header at all, so a 401
                    must not be reported as "rejected" — nothing was offered to reject. */
    juce::String describeStatus (int status, const juce::String& key);

    /** Unwraps the `{"data": …, "code": …}` envelope the servers use. `data` is
        sometimes absent, in which case the body itself is the payload. */
    juce::var unwrapEnvelope (const juce::var& parsed);
}

} // namespace acemusic
