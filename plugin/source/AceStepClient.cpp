#include "AceStepClient.h"
#include "HttpSupport.h"

namespace acemusic
{

using namespace acemusic::Http;


juce::StringArray parseModelNames (const juce::String& responseBody)
{
    juce::StringArray names;

    const auto payload = unwrapEnvelope (juce::JSON::parse (responseBody));
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

    const auto endpoint = prepareEndpoint (baseUrl, apiKey, "/v1/stats");

    if (endpoint.error.isNotEmpty())
    {
        result.errorMessage = endpoint.error;
        return result;
    }

    if (stopRequested())
    {
        result.cancelled = true;
        return result;
    }

    juce::WebInputStream stream (endpoint.url, false);
    configure (stream, endpoint, timeoutMs);

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

    if (const auto statusError = describeStatus (stream.getStatusCode(), endpoint.key);
        statusError.isNotEmpty())
    {
        result.errorMessage = statusError;
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

//==============================================================================
namespace
{
    /** Runs a POST and returns the body, or an error. */
    struct PostOutcome
    {
        juce::String body;
        juce::String error;
        bool cancelled = false;
    };

    PostOutcome post (const Endpoint& endpoint,
                      const juce::String& json,
                      const std::function<bool()>& shouldCancel,
                      int timeoutMs)
    {
        PostOutcome outcome;

        const auto stopRequested = [&shouldCancel] { return shouldCancel != nullptr && shouldCancel(); };

        if (stopRequested())
        {
            outcome.cancelled = true;
            return outcome;
        }

        // The body lives on the URL, not the stream — juce::WebInputStream reads it
        // from there when constructed with isPost = true.
        juce::WebInputStream stream (endpoint.url.withPOSTData (json), true);
        configure (stream, endpoint, timeoutMs);
        stream.withExtraHeaders ("Content-Type: application/json");

        if (! stream.connect (nullptr))
        {
            if (stopRequested())
                outcome.cancelled = true;
            else
                outcome.error = "Server unreachable";

            return outcome;
        }

        if (const auto statusError = describeStatus (stream.getStatusCode(), endpoint.key);
            statusError.isNotEmpty())
        {
            outcome.error = statusError;
            return outcome;
        }

        outcome.body = stream.readEntireStreamAsString();
        return outcome;
    }
}

SubmitResult submitGeneration (const juce::String& baseUrl,
                               const juce::String& apiKey,
                               const juce::String& payloadJson,
                               std::function<bool()> shouldCancel,
                               int timeoutMs)
{
    SubmitResult result;

    const auto endpoint = prepareEndpoint (baseUrl, apiKey, "/release_task");

    if (endpoint.error.isNotEmpty())
    {
        result.errorMessage = endpoint.error;
        return result;
    }

    const auto outcome = post (endpoint, payloadJson, shouldCancel, timeoutMs);

    if (outcome.cancelled)
    {
        result.cancelled = true;
        return result;
    }

    if (outcome.error.isNotEmpty())
    {
        result.errorMessage = outcome.error;
        return result;
    }

    const auto payload = unwrapEnvelope (juce::JSON::parse (outcome.body));

    if (auto* object = payload.getDynamicObject())
    {
        // The Python client accepts either spelling, so the plugin does too.
        auto id = object->getProperty ("task_id").toString();

        if (id.isEmpty())
            id = object->getProperty ("id").toString();

        if (id.isNotEmpty())
        {
            result.ok = true;
            result.taskId = id;
            return result;
        }
    }

    result.errorMessage = "Server accepted the request but returned no task id";
    return result;
}

TaskStatus parseTaskStatus (const juce::String& responseBody, const juce::String& baseUrl)
{
    TaskStatus status;

    const auto payload = unwrapEnvelope (juce::JSON::parse (responseBody));

    // /query_result answers with a list, one entry per requested id.
    const juce::var* item = nullptr;

    if (auto* array = payload.getArray(); array != nullptr && ! array->isEmpty())
        item = &array->getReference (0);
    else if (payload.getDynamicObject() != nullptr)
        item = &payload;

    if (item == nullptr || item->getDynamicObject() == nullptr)
    {
        status.errorMessage = "Could not read the task status from the server";
        return status;
    }

    status.ok = true;

    // The server sends an integer (0 queued/running, 1 succeeded, 2 failed) but the
    // Python client tolerates a string, so match that.
    const auto rawStatus = item->getProperty ("status", 0);

    if (rawStatus.isString())
    {
        const auto text = rawStatus.toString().toLowerCase();
        status.state = text == "completed" ? TaskStatus::State::completed
                     : text == "failed"    ? TaskStatus::State::failed
                                           : TaskStatus::State::pending;
    }
    else
    {
        switch ((int) rawStatus)
        {
            case 1:  status.state = TaskStatus::State::completed; break;
            case 2:  status.state = TaskStatus::State::failed;    break;
            default: status.state = TaskStatus::State::pending;   break;
        }
    }

    const auto errorText = item->getProperty ("error", juce::var()).toString();

    if (status.state == TaskStatus::State::failed)
        status.errorMessage = errorText.isNotEmpty() ? errorText : juce::String ("Generation failed");

    // `result` is a JSON *string* holding [{"file": "/v1/audio?path=..."}].
    const auto rawResult = item->getProperty ("result", juce::var());
    const auto clips = rawResult.isString() ? juce::JSON::parse (rawResult.toString()) : rawResult;

    if (auto* clipArray = clips.getArray())
    {
        const auto base = baseUrl.trim().trimCharactersAtEnd ("/");

        for (const auto& clip : *clipArray)
        {
            const auto file = clip.getProperty ("file", juce::var()).toString();

            if (file.isEmpty())
                continue;

            status.audioUrls.add (file.startsWithChar ('/') ? base + file : file);
        }
    }

    return status;
}

TaskStatus queryTask (const juce::String& baseUrl,
                      const juce::String& apiKey,
                      const juce::String& taskId,
                      std::function<bool()> shouldCancel,
                      int timeoutMs)
{
    TaskStatus status;

    const auto endpoint = prepareEndpoint (baseUrl, apiKey, "/query_result");

    if (endpoint.error.isNotEmpty())
    {
        status.errorMessage = endpoint.error;
        return status;
    }

    auto* body = new juce::DynamicObject();
    juce::Array<juce::var> ids;
    ids.add (taskId);
    body->setProperty ("task_id_list", ids);

    const auto outcome = post (endpoint, juce::JSON::toString (juce::var (body), true),
                               shouldCancel, timeoutMs);

    if (outcome.cancelled)
    {
        status.cancelled = true;
        return status;
    }

    if (outcome.error.isNotEmpty())
    {
        status.errorMessage = outcome.error;
        return status;
    }

    return parseTaskStatus (outcome.body, baseUrl);
}

juce::String downloadAudio (const juce::String& audioUrl,
                            const juce::String& apiKey,
                            const juce::File& destination,
                            std::function<bool()> shouldCancel,
                            int timeoutMs)
{
    const auto stopRequested = [&shouldCancel] { return shouldCancel != nullptr && shouldCancel(); };

    if (audioUrl.trim().isEmpty())
        return "No audio URL to download";

    if (stopRequested())
        return {};

    // The audio URL is already absolute, so prepareEndpoint's base-plus-path shape
    // does not fit — but the key still goes through the same sanitiser, and the
    // stream through the same configure(), rather than being hand-rolled a fourth time.
    Endpoint endpoint;
    endpoint.url = juce::URL (audioUrl.trim());

    const auto scheme = endpoint.url.getScheme().toLowerCase();

    if (! endpoint.url.isWellFormed() || (scheme != "http" && scheme != "https"))
        return "Audio URL is not a valid http(s) address";

    endpoint.key = sanitiseKey (apiKey, endpoint.error);

    if (endpoint.error.isNotEmpty())
        return endpoint.error;

    juce::WebInputStream stream (endpoint.url, false);
    configure (stream, endpoint, timeoutMs);

    if (! stream.connect (nullptr))
        return stopRequested() ? juce::String() : juce::String ("Could not reach the audio URL");

    if (const auto statusError = describeStatus (stream.getStatusCode(), endpoint.key);
        statusError.isNotEmpty())
        return statusError;

    // Known up front when the server sends Content-Length; -1 when it does not.
    const auto expectedBytes = stream.getTotalLength();

    destination.getParentDirectory().createDirectory();

    // Write to a temporary and move on success, so a cancelled or failed download
    // never leaves a half-written file that looks like a usable clip.
    const auto temp = destination.getSiblingFile (destination.getFileName() + ".part");
    temp.deleteFile();

    {
        juce::FileOutputStream out (temp);

        if (out.failedToOpen())
            return "Could not write to " + destination.getFullPathName();

        juce::HeapBlock<char> buffer (65536);

        for (;;)
        {
            if (stopRequested())
            {
                stream.cancel();
                temp.deleteFile();
                return {};
            }

            const auto read = stream.read (buffer.get(), 65536);

            if (read <= 0)
                break;

            if (! out.write (buffer.get(), (size_t) read))
            {
                temp.deleteFile();
                return "Ran out of space writing " + destination.getFileName();
            }
        }
    }

    if (temp.getSize() == 0)
    {
        temp.deleteFile();
        return "The server returned an empty audio file";
    }

    // A dropped connection mid-transfer just ends the read loop, which would
    // otherwise move a truncated file into place and call it a clip.
    if (expectedBytes > 0 && temp.getSize() < expectedBytes)
    {
        const auto got = temp.getSize();
        temp.deleteFile();
        return "Download was cut short (" + juce::String (got) + " of "
             + juce::String (expectedBytes) + " bytes)";
    }

    destination.deleteFile();

    if (! temp.moveFileTo (destination))
    {
        temp.deleteFile();
        return "Could not save " + destination.getFileName();
    }

    return {};
}

} // namespace acemusic
