#include "GenerationRequest.h"

namespace acemusic
{

class GenerationRequestTests final : public juce::UnitTest
{
public:
    GenerationRequestTests()
        : juce::UnitTest ("GenerationRequest", "acemusic")
    {
    }

    /** The payload as an object, so tests can ask what was and wasn't sent. */
    static juce::DynamicObject* payloadOf (const GenerationRequest& request, juce::var& keepAlive)
    {
        keepAlive = request.toPayload();
        return keepAlive.getDynamicObject();
    }

    static GenerationRequest minimalRequest()
    {
        GenerationRequest request;
        request.prompt = "warm analogue synth pad";
        return request;
    }

    void runTest() override
    {
        beginTest ("quality presets use the documented inference-step counts");
        {
            // src/acemusic/client.py: "inference_steps: Number of diffusion steps
            // (Turbo: 8, Standard: 32-64)." These are not ours to invent.
            expectEquals (GenerationRequest::inferenceStepsFor (GenerationRequest::Quality::turbo), 8);

            const auto standard = GenerationRequest::inferenceStepsFor (GenerationRequest::Quality::standard);
            expect (standard >= 32 && standard <= 64,
                    "Standard is outside the documented 32-64 range: " + juce::String (standard));

            expect (GenerationRequest::inferenceStepsFor (GenerationRequest::Quality::high) > standard,
                    "High should use more steps than Standard");
        }

        beginTest ("offers 50+ vocal languages and a full set of keys");
        {
            const auto languages = GenerationRequest::vocalLanguages();
            expect (languages.size() >= 50,
                    "only " + juce::String (languages.size()) + " languages offered");

            juce::StringArray deduped (languages);
            deduped.removeDuplicates (false);
            expectEquals (deduped.size(), languages.size(), "the language list has duplicates");

            const auto keys = GenerationRequest::musicalKeys();
            expectEquals (keys[0], juce::String ("Any"), "the key list must open with Any");
            expectEquals (keys.size(), 25, "expected Any + 12 tonics x major/minor");
        }

        beginTest ("a minimal request sends the required fields");
        {
            juce::var keepAlive;
            auto* payload = payloadOf (minimalRequest(), keepAlive);

            expect (payload != nullptr);
            expectEquals (payload->getProperty ("prompt").toString(), juce::String ("warm analogue synth pad"));
            expectEquals ((int) payload->getProperty ("batch_size"), 2, "should ask for 2 clips");
            expectEquals ((int) payload->getProperty ("audio_duration"), 60);
            expectEquals ((int) payload->getProperty ("inference_steps"), 48);
        }

        beginTest ("Auto / Any / Random are omitted rather than sent as sentinels");
        {
            // The server reads an absent key as "you choose"; -1 or "" would be taken
            // literally, so the sentinels must never reach the wire.
            juce::var keepAlive;
            auto* payload = payloadOf (minimalRequest(), keepAlive);

            for (const auto* absent : { "bpm", "key", "seed", "lyrics", "vocal_language",
                                        "instrumental", "task_type", "src_audio_path", "model" })
            {
                expect (! payload->hasProperty (absent),
                        juce::String ("sent ") + absent + " when it should have been omitted");
            }
        }

        beginTest ("every populated control reaches the payload");
        {
            auto request = minimalRequest();
            request.lyrics         = "[Verse]\nSomething true";
            request.vocalLanguage  = "Japanese";
            request.instrumental   = true;
            request.bpm            = 128;
            request.key            = "F# minor";
            request.durationSeconds = 90;
            request.seed           = 4242;
            request.quality        = GenerationRequest::Quality::high;
            request.model          = "ace-step-1.5";
            request.clipCount      = 2;

            juce::var keepAlive;
            auto* payload = payloadOf (request, keepAlive);

            expectEquals (payload->getProperty ("lyrics").toString(), request.lyrics);
            expectEquals (payload->getProperty ("vocal_language").toString(), juce::String ("Japanese"));
            expect ((bool) payload->getProperty ("instrumental"));
            expectEquals ((int) payload->getProperty ("bpm"), 128);
            expectEquals (payload->getProperty ("key").toString(), juce::String ("F# minor"));
            expectEquals ((int) payload->getProperty ("audio_duration"), 90);
            expectEquals ((juce::int64) payload->getProperty ("seed"), (juce::int64) 4242);
            expectEquals ((int) payload->getProperty ("inference_steps"), 120);
            expectEquals (payload->getProperty ("model").toString(), juce::String ("ace-step-1.5"));
        }

        beginTest ("seed 0 is a real seed, not 'Random'");
        {
            // -1 is the sentinel; 0 is a value the user can legitimately choose, and
            // dropping it would silently randomise a run they wanted reproducible.
            auto request = minimalRequest();
            request.seed = 0;

            juce::var keepAlive;
            auto* payload = payloadOf (request, keepAlive);

            expect (payload->hasProperty ("seed"), "seed 0 was dropped as if it were Random");
            expectEquals ((juce::int64) payload->getProperty ("seed"), (juce::int64) 0);
        }

        beginTest ("text-to-music omits task_type, cover sends it with a source");
        {
            juce::var textVar;
            auto* textPayload = payloadOf (minimalRequest(), textVar);

            // The Python client omits task_type for text2music because that is the
            // server's default; sending it would be a behaviour change, not a no-op.
            expect (! textPayload->hasProperty ("task_type"),
                    "sent task_type for text-to-music");

            auto cover = minimalRequest();
            cover.mode = GenerationRequest::Mode::cover;
            cover.sourceAudioPath = "/tmp/source.wav";

            juce::var coverVar;
            auto* coverPayload = payloadOf (cover, coverVar);

            expectEquals (coverPayload->getProperty ("task_type").toString(), juce::String ("cover"));
            expectEquals (coverPayload->getProperty ("src_audio_path").toString(),
                          juce::String ("/tmp/source.wav"));
        }

        beginTest ("validation catches what the server would only reject later");
        {
            GenerationRequest blank;
            expect (! blank.isValid(), "an empty prompt was accepted");
            expect (blank.findProblem().containsIgnoreCase ("prompt"), blank.findProblem());

            auto whitespacePrompt = minimalRequest();
            whitespacePrompt.prompt = "   \t ";
            expect (! whitespacePrompt.isValid(), "a whitespace-only prompt was accepted");

            auto zeroDuration = minimalRequest();
            zeroDuration.durationSeconds = 0;
            expect (! zeroDuration.isValid(), "a zero duration was accepted");

            auto coverWithoutSource = minimalRequest();
            coverWithoutSource.mode = GenerationRequest::Mode::cover;
            expect (! coverWithoutSource.isValid(), "cover mode without a source was accepted");
            expect (coverWithoutSource.findProblem().containsIgnoreCase ("source"),
                    coverWithoutSource.findProblem());

            expect (minimalRequest().isValid(), minimalRequest().findProblem());
        }

        beginTest ("the payload serialises to JSON the server can parse");
        {
            auto request = minimalRequest();
            request.lyrics = "[Chorus]\nQuoted \"text\" and a \\ backslash";

            const auto json = request.toPayloadJson();
            const auto reparsed = juce::JSON::parse (json);

            expect (reparsed.getDynamicObject() != nullptr, "payload did not round-trip: " + json);
            expectEquals (reparsed.getProperty ("lyrics", juce::var()).toString(), request.lyrics,
                          "lyrics were mangled by JSON encoding");
        }

        //======================================================================
        // US-24.3 — modes that need a source.

        beginTest ("every mode but Text to Music needs source audio");
        {
            expect (! GenerationRequest::needsSourceAudio (GenerationRequest::Mode::textToMusic));
            expect (GenerationRequest::needsSourceAudio (GenerationRequest::Mode::cover));
            expect (GenerationRequest::needsSourceAudio (GenerationRequest::Mode::complete));
            expect (GenerationRequest::needsSourceAudio (GenerationRequest::Mode::repaint));

            GenerationRequest request;
            request.prompt = "anything";
            request.mode = GenerationRequest::Mode::complete;

            expect (! request.isValid(), "Complete was submittable with no sketch");
            expect (request.findProblem().containsIgnoreCase ("Complete"),
                    "the problem does not name the mode: " + request.findProblem());

            request.sourceAudioPath = "/tmp/sketch.wav";
            expect (request.isValid());
        }

        beginTest ("the task_type sent matches what ACE-Step expects");
        {
            // These strings are ACE-Step's, not ours: see TaskType in
            // src/acemusic/client.py. Getting one wrong is a silent server-side default.
            expect (GenerationRequest::taskTypeFor (GenerationRequest::Mode::textToMusic).isEmpty(),
                    "text2music should be omitted, as the Python client omits it");
            expectEquals (GenerationRequest::taskTypeFor (GenerationRequest::Mode::cover),
                          juce::String ("cover"));
            expectEquals (GenerationRequest::taskTypeFor (GenerationRequest::Mode::complete),
                          juce::String ("complete"));
            expectEquals (GenerationRequest::taskTypeFor (GenerationRequest::Mode::repaint),
                          juce::String ("repaint"));
        }

        beginTest ("Complete sends the rendered sketch as src_audio_path");
        {
            GenerationRequest request;
            request.prompt = "flesh this out";
            request.mode = GenerationRequest::Mode::complete;
            request.sourceAudioPath = "/tmp/midi-sketch.wav";

            const juce::var payload = request.toPayload();
            auto* object = payload.getDynamicObject();
            expect (object != nullptr);
            expectEquals (object->getProperty ("task_type").toString(), juce::String ("complete"));
            expectEquals (object->getProperty ("src_audio_path").toString(),
                          juce::String ("/tmp/midi-sketch.wav"));
            expect (! object->hasProperty ("repainting_start"),
                    "a non-repaint request carried a repaint range");
        }

        beginTest ("Repaint carries its range, and omits it when it is not set");
        {
            GenerationRequest request;
            request.prompt = "redo this bit";
            request.mode = GenerationRequest::Mode::repaint;
            request.sourceAudioPath = "/tmp/sidechain.wav";

            {
                const juce::var payload = request.toPayload();
                auto* object = payload.getDynamicObject();
                expect (! object->hasProperty ("repainting_start"),
                        "an unset range was sent rather than omitted");
                expect (! object->hasProperty ("repainting_end"));
            }

            request.repaintStartSeconds = 4.0;
            request.repaintEndSeconds = 12.0;
            expect (request.hasRepaintRange());

            {
                const juce::var payload = request.toPayload();
                auto* object = payload.getDynamicObject();
                expectEquals ((double) object->getProperty ("repainting_start"), 4.0);
                expectEquals ((double) object->getProperty ("repainting_end"), 12.0);
            }

            // A backwards or zero-length range is not a range.
            request.repaintEndSeconds = 4.0;
            expect (! request.hasRepaintRange(), "a zero-length range was accepted");
            request.repaintEndSeconds = 1.0;
            expect (! request.hasRepaintRange(), "a backwards range was accepted");
        }
    }
};

static GenerationRequestTests generationRequestTests;

} // namespace acemusic
