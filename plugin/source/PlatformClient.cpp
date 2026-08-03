#include "PlatformClient.h"
#include "HttpSupport.h"

namespace acemusic
{
namespace Platform
{

namespace
{
    /** Everything on the platform API hangs off this. */
    constexpr const char* apiPrefix = "/api/v1";

    bool wasCancelled (const std::function<bool()>& shouldCancel)
    {
        return shouldCancel != nullptr && shouldCancel();
    }

    Result cancelledResult()
    {
        Result result;
        result.cancelled = true;
        return result;
    }

    Result failure (const juce::String& message)
    {
        Result result;
        result.errorMessage = message;
        return result;
    }

    /** Runs a GET and hands back the body, or fills `result` with the reason it could
        not. @returns false when the caller should give up. */
    bool fetch (const juce::String& baseUrl,
                const juce::String& apiKey,
                const juce::String& path,
                const std::function<bool()>& shouldCancel,
                int timeoutMs,
                juce::String& bodyOut,
                Result& result)
    {
        if (const auto problem = findUrlProblem (baseUrl); problem.isNotEmpty())
        {
            result = failure (problem);
            return false;
        }

        const auto endpoint = Http::prepareEndpoint (baseUrl, apiKey, path);

        if (endpoint.error.isNotEmpty())
        {
            result = failure (endpoint.error);
            return false;
        }

        if (wasCancelled (shouldCancel))
        {
            result = cancelledResult();
            return false;
        }

        juce::WebInputStream stream (endpoint.url, false);
        Http::configure (stream, endpoint, timeoutMs);

        if (! stream.connect (nullptr))
        {
            // A cancel during the blocking connect looks like a failure from here;
            // asking again is what tells the two apart.
            result = wasCancelled (shouldCancel)
                       ? cancelledResult()
                       : failure ("Could not reach the platform at " + baseUrl.trim());
            return false;
        }

        if (const auto status = Http::describeStatus (stream.getStatusCode(), endpoint.key);
            status.isNotEmpty())
        {
            result = failure (status);
            return false;
        }

        bodyOut = stream.readEntireStreamAsString();
        return true;
    }

    juce::String textOf (const juce::var& object, const char* key)
    {
        return object.getProperty (key, juce::var()).toString();
    }
}

//==============================================================================
juce::String findUrlProblem (const juce::String& baseUrl)
{
    const auto trimmed = baseUrl.trim();

    if (trimmed.isEmpty())
        return "No platform URL set";

    if (! hasTlsSupport() && trimmed.startsWithIgnoreCase ("https:"))
    {
        // Caught here rather than at the socket: on a Linux build without libcurl,
        // JUCE cannot do TLS at all, and the failure would otherwise surface as a
        // connection error the user has no way to act on.
        return "This build cannot use https:// - it was built without libcurl. "
               "Install libcurl4-openssl-dev and rebuild, or use an http:// platform URL.";
    }

    return {};
}

//==============================================================================
Result listWorkspaces (const juce::String& baseUrl,
                       const juce::String& apiKey,
                       std::function<bool()> shouldCancel,
                       int timeoutMs)
{
    Result result;
    juce::String body;

    if (! fetch (baseUrl, apiKey, juce::String (apiPrefix) + "/workspaces", shouldCancel, timeoutMs, body, result))
        return result;

    const auto payload = Http::unwrapEnvelope (juce::JSON::parse (body));

    // The listing is either a bare array or {"workspaces": [...]}; accept both rather
    // than depending on which envelope shape this endpoint happens to use.
    const juce::Array<juce::var>* items = payload.getArray();

    if (items == nullptr)
        items = payload.getProperty ("workspaces", juce::var()).getArray();

    if (items == nullptr)
        return failure ("The platform returned no workspace list");

    for (const auto& item : *items)
    {
        Workspace workspace;
        workspace.id = textOf (item, "id");
        workspace.name = textOf (item, "name");

        if (workspace.id.isNotEmpty())
            result.workspaces.add (workspace);
    }

    result.ok = true;
    return result;
}

Result listClips (const juce::String& baseUrl,
                  const juce::String& apiKey,
                  const juce::String& workspaceId,
                  const juce::String& search,
                  int page,
                  int perPage,
                  std::function<bool()> shouldCancel,
                  int timeoutMs)
{
    juce::String path { juce::String (apiPrefix) + "/clips?page=" + juce::String (juce::jmax (1, page))
                            + "&per_page=" + juce::String (juce::jlimit (1, 100, perPage)) };

    // Escaped, because both are user text: a workspace name with an & in it would
    // otherwise inject a query parameter.
    if (workspaceId.trim().isNotEmpty())
        path << "&workspace_id=" << juce::URL::addEscapeChars (workspaceId.trim(), false);

    if (search.trim().isNotEmpty())
        path << "&search=" << juce::URL::addEscapeChars (search.trim(), false);

    Result result;
    juce::String body;

    if (! fetch (baseUrl, apiKey, path, shouldCancel, timeoutMs, body, result))
        return result;

    const auto payload = Http::unwrapEnvelope (juce::JSON::parse (body));
    const juce::Array<juce::var>* items = payload.getProperty ("clips", juce::var()).getArray();

    if (items == nullptr)
        items = payload.getArray();

    if (items == nullptr)
        return failure ("The platform returned no clip list");

    for (const auto& item : *items)
    {
        Clip clip;
        clip.id = textOf (item, "id");
        clip.title = textOf (item, "title");
        clip.format = textOf (item, "format");
        clip.duration = (double) item.getProperty ("duration", juce::var (0.0));
        clip.bpm = (int) item.getProperty ("bpm", juce::var (0));
        clip.key = textOf (item, "key");
        clip.createdAt = textOf (item, "created_at");

        if (auto* tags = item.getProperty ("style_tags", juce::var()).getArray())
            for (const auto& tag : *tags)
                clip.styleTags.add (tag.toString());

        if (clip.id.isNotEmpty())
            result.clips.add (clip);
    }

    result.total = (int) payload.getProperty ("total", juce::var (result.clips.size()));
    result.ok = true;
    return result;
}

Result downloadClip (const juce::String& baseUrl,
                     const juce::String& apiKey,
                     const juce::String& clipId,
                     const juce::File& destination,
                     std::function<bool()> shouldCancel,
                     int timeoutMs)
{
    if (clipId.trim().isEmpty())
        return failure ("No clip selected");

    if (const auto problem = findUrlProblem (baseUrl); problem.isNotEmpty())
        return failure (problem);

    const auto path = juce::String (apiPrefix) + "/clips/"
                        + juce::URL::addEscapeChars (clipId.trim(), false) + "/audio";
    const auto endpoint = Http::prepareEndpoint (baseUrl, apiKey, path);

    if (endpoint.error.isNotEmpty())
        return failure (endpoint.error);

    if (wasCancelled (shouldCancel))
        return cancelledResult();

    juce::WebInputStream stream (endpoint.url, false);
    Http::configure (stream, endpoint, timeoutMs);

    if (! stream.connect (nullptr))
    {
        return wasCancelled (shouldCancel)
                 ? cancelledResult()
                 : failure ("Could not reach the platform at " + baseUrl.trim());
    }

    if (const auto status = Http::describeStatus (stream.getStatusCode(), endpoint.key); status.isNotEmpty())
        return failure (status);

    destination.getParentDirectory().createDirectory();

    // Downloaded to a temporary and moved into place, so a cancelled or failed
    // transfer never leaves a truncated file that later looks like a finished clip.
    const auto partial = destination.getSiblingFile (destination.getFileName() + ".partial");
    partial.deleteFile();

    {
        juce::FileOutputStream out (partial);

        if (out.failedToOpen())
            return failure ("Could not write to " + destination.getFullPathName());

        juce::HeapBlock<char> buffer (32768);

        while (! stream.isExhausted())
        {
            if (wasCancelled (shouldCancel))
            {
                partial.deleteFile();
                return cancelledResult();
            }

            const auto read = stream.read (buffer, 32768);

            if (read <= 0)
                break;

            if (! out.write (buffer, (size_t) read))
            {
                partial.deleteFile();
                return failure ("Ran out of space writing " + destination.getFileName());
            }
        }
    }

    if (partial.getSize() <= 0)
    {
        partial.deleteFile();
        return failure ("The platform returned an empty clip");
    }

    destination.deleteFile();

    if (! partial.moveFileTo (destination))
    {
        partial.deleteFile();
        return failure ("Could not save the clip to " + destination.getFullPathName());
    }

    Result result;
    result.ok = true;
    result.clipId = clipId.trim();
    result.file = destination;
    return result;
}

Result uploadClip (const juce::String& baseUrl,
                   const juce::String& apiKey,
                   const juce::String& workspaceId,
                   const juce::File& audio,
                   const juce::String& title,
                   int bpm,
                   const juce::String& key,
                   double durationSeconds,
                   std::function<bool()> shouldCancel,
                   int timeoutMs)
{
    if (workspaceId.trim().isEmpty())
        return failure ("Choose a workspace to push to");

    if (! audio.existsAsFile())
        return failure ("That clip is no longer on disk");

    if (const auto problem = findUrlProblem (baseUrl); problem.isNotEmpty())
        return failure (problem);

    const auto endpoint = Http::prepareEndpoint (baseUrl, apiKey, juce::String (apiPrefix) + "/clips/upload");

    if (endpoint.error.isNotEmpty())
        return failure (endpoint.error);

    if (wasCancelled (shouldCancel))
        return cancelledResult();

    // Multipart, matching the endpoint's UploadFile + Form fields. JUCE builds the
    // body; the file is streamed rather than read into memory here.
    auto url = endpoint.url
                   .withParameter ("workspace_id", workspaceId.trim())
                   .withFileToUpload ("file", audio, "application/octet-stream");

    if (title.trim().isNotEmpty())
        url = url.withParameter ("title", title.trim());

    if (bpm > 0)
        url = url.withParameter ("bpm", juce::String (bpm));

    if (key.trim().isNotEmpty())
        url = url.withParameter ("key", key.trim());

    if (durationSeconds > 0.0)
        url = url.withParameter ("duration", juce::String (durationSeconds, 3));

    juce::WebInputStream stream (url, true);   // true: POST
    Http::configure (stream, endpoint, timeoutMs);

    if (! stream.connect (nullptr))
    {
        return wasCancelled (shouldCancel)
                 ? cancelledResult()
                 : failure ("Could not reach the platform at " + baseUrl.trim());
    }

    if (const auto status = Http::describeStatus (stream.getStatusCode(), endpoint.key); status.isNotEmpty())
        return failure (status);

    const auto payload = Http::unwrapEnvelope (juce::JSON::parse (stream.readEntireStreamAsString()));

    Result result;
    result.clipId = textOf (payload, "id");

    if (result.clipId.isEmpty())
        return failure ("The platform accepted the upload but returned no clip id");

    result.ok = true;
    return result;
}

} // namespace Platform
} // namespace acemusic
