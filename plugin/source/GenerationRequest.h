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
    /** How the generation is seeded.

        Every mode but textToMusic needs a source audio file. That is a property of the
        server, not a choice: ACE-Step's cover / complete / repaint task types all take
        `src_audio_path`, and it has no MIDI input at all — a MIDI sketch reaches
        `complete` as audio rendered by MidiCapture. */
    enum class Mode
    {
        textToMusic,
        cover,      ///< restyle a reference: the sidechain capture
        complete,   ///< flesh out a sketch: the MIDI capture, rendered
        repaint     ///< regenerate a time range of a reference
    };

    /** True when `mode` cannot be submitted without sourceAudioPath. */
    static bool needsSourceAudio (Mode) noexcept;

    /** The server's `task_type` for `mode`, or empty for the server default. */
    static juce::String taskTypeFor (Mode) noexcept;

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

    /** Server-side path to the source audio, for every mode but Text to Music. */
    juce::String sourceAudioPath;

    /** Repaint only: the range of the source to regenerate, in seconds. A negative
        start means "not set", and the range is omitted so the server decides. */
    double repaintStartSeconds = -1.0;
    double repaintEndSeconds = -1.0;

    bool hasRepaintRange() const;

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

    /** Every mode, in menu order. */
    static juce::Array<Mode> allModes();

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
