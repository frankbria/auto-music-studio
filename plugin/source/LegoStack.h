#pragma once

#include <juce_audio_formats/juce_audio_formats.h>

namespace acemusic
{

/**
    The layers of a Lego-mode build, and the context audio the next layer is generated
    against.

    ACE-Step's `lego` task type is "generate a specific instrument track in context": it
    takes the music so far as `src_audio_path` and an instruction naming the track to add.
    This owns the "music so far" half — the ordered layers, and their mixdown.

    **Regenerating a layer uses the mix of the *others*.** A bass being replaced should fit
    the drums it sits under, not the bass it is replacing, so the layer under revision is
    excluded from its own context. That is the whole reason this is a type rather than a
    juce::Array in the panel.
*/
class LegoStack
{
public:
    LegoStack() = default;

    /** One generated layer. */
    struct Layer
    {
        /** ACE-Step track name, e.g. "bass". See trackNames(). */
        juce::String track;

        /** What the musician asked for, e.g. "a funky bass line". */
        juce::String prompt;

        juce::File clip;

        /** Muted layers stay in the list but are left out of the context mix, so a part
            can be auditioned out without losing it. */
        bool enabled = true;
    };

    //==============================================================================
    /** The instrument tracks ACE-Step recognises. These are its `TRACK_NAMES`, not ours;
        a name outside this list produces an instruction the model was not trained on. */
    static juce::StringArray trackNames();

    /** The instruction that tells the server which track to generate. Matches ACE-Step's
        own `TASK_INSTRUCTIONS["lego"]` template. */
    static juce::String instructionFor (const juce::String& track);

    //==============================================================================
    void addLayer (const juce::String& track, const juce::String& prompt, const juce::File& clip);

    /** Replaces the clip of an existing layer, leaving every other layer untouched.
        @returns false if `index` is out of range. */
    bool replaceLayer (int index, const juce::File& clip);

    bool removeLayer (int index);
    bool setLayerEnabled (int index, bool enabled);

    const juce::Array<Layer>& getLayers() const noexcept      { return layers; }
    int getNumLayers() const noexcept                         { return layers.size(); }
    void clear();

    //==============================================================================
    /** Mixes every enabled layer, optionally excluding one.

        @param excludeIndex  the layer being regenerated, or < 0 to include them all
        @returns an empty buffer when nothing would be in the mix */
    juce::AudioBuffer<float> mixContext (juce::AudioFormatManager&, int excludeIndex = -1) const;

    /** Writes the context mix to `destination`.
        @returns false when there is nothing to mix or the write failed. */
    bool writeContext (const juce::File& destination,
                       juce::AudioFormatManager&,
                       int excludeIndex = -1) const;

    /** True when a generation would have context to work from — i.e. the next layer is a
        `lego` task rather than an ordinary text-to-music one. */
    bool hasContext (int excludeIndex = -1) const;

    /** The sample rate the context mix is written at. Taken from the first readable
        layer so the mix matches the material rather than a guess. */
    double getContextSampleRate (juce::AudioFormatManager&) const;

private:
    juce::Array<Layer> layers;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (LegoStack)
};

} // namespace acemusic
