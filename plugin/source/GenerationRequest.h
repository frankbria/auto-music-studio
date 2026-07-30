#pragma once

#include <juce_core/juce_core.h>

namespace acemusic
{

/**
    Everything the generation panel collects, and how it becomes a `/release_task`
    body.

    Field names and semantics mirror `AceStepClient.submit_task` in
    `src/acemusic/client.py` — this is the same API the CLI and platform already
    drive, so the plugin should not invent its own dialect.
*/
struct GenerationRequest
{
    /** Text-to-Music or Cover. Cover needs a source reference. */
    enum class Mode
    {
        textToMusic,
        cover
    };

    /** Maps to `inference_steps`. The values come from the documented ranges in
        `src/acemusic/client.py` ("Turbo: 8, Standard: 32–64"), not from guesswork. */
    enum class Quality
    {
        turbo,
        standard,
        high
    };

    juce::String prompt;
    juce::String lyrics;
    juce::String vocalLanguage;      ///< display name, e.g. "English"; empty = omit
    bool instrumental = false;

    /** < 0 means "Auto" — omitted so the server chooses. */
    int bpm = -1;

    /** Empty means "Any" — omitted so the server chooses. */
    juce::String key;

    int durationSeconds = 60;

    /** < 0 means "Random" — omitted so the server seeds itself. */
    juce::int64 seed = -1;

    Quality quality = Quality::standard;
    Mode mode = Mode::textToMusic;

    /** Server-side path to the source audio, for Cover mode. */
    juce::String sourceAudioPath;

    /** Model name from the connection panel; empty = let the server decide. */
    juce::String model;

    /** How many clips to ask for. The story wants 2. */
    int clipCount = 2;

    //==============================================================================
    static int inferenceStepsFor (Quality) noexcept;
    static juce::String toString (Quality) noexcept;
    static juce::String toString (Mode) noexcept;

    /** Every quality preset, in menu order. */
    static juce::Array<Quality> allQualities();

    /** Vocal languages offered by the panel. */
    static juce::StringArray vocalLanguages();

    /** Musical keys offered by the panel; the first entry is "Any". */
    static juce::StringArray musicalKeys();

    //==============================================================================
    /** Why this request cannot be sent, or empty if it can. */
    juce::String findProblem() const;

    bool isValid() const                                      { return findProblem().isEmpty(); }

    /** The `/release_task` body. Optional fields are *omitted* rather than sent as
        empty or sentinel values, matching what the Python client does — the server
        treats an absent key as "you choose". */
    juce::var toPayload() const;

    /** The payload as the JSON text that actually goes on the wire. */
    juce::String toPayloadJson() const;
};

} // namespace acemusic
