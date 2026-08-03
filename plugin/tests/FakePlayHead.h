#pragma once

#include <juce_audio_basics/juce_audio_basics.h>

namespace acemusic::test
{

/**
    Stands in for the host's transport. `reportsPosition = false` is the host that
    hands the plugin a play head but tells it nothing, which is what the Standalone
    build and several real hosts do — that path has to be exercised, not assumed away.
*/
class FakePlayHead final : public juce::AudioPlayHead
{
public:
    juce::Optional<PositionInfo> getPosition() const override
    {
        if (! reportsPosition)
            return {};

        PositionInfo info;

        if (bpm > 0.0)
            info.setBpm (bpm);

        if (timeInSeconds >= 0.0)
            info.setTimeInSeconds (timeInSeconds);

        if (loopEndPpq > loopStartPpq)
            info.setLoopPoints (LoopPoints { loopStartPpq, loopEndPpq });

        if (timeSigNumerator > 0 && timeSigDenominator > 0)
            info.setTimeSignature (TimeSignature { timeSigNumerator, timeSigDenominator });

        return info;
    }

    bool reportsPosition = true;

    /** <= 0 means "the host publishes no tempo". */
    double bpm = 120.0;

    /** < 0 means "the host publishes no position". */
    double timeInSeconds = 0.0;

    /** The loop / cycle range in quarter notes. Equal values mean "no loop range",
        which is what a host with no cycle locators set reports. */
    double loopStartPpq = 0.0;
    double loopEndPpq = 0.0;

    /** 0/0 means "the host publishes no time signature". */
    int timeSigNumerator = 0;
    int timeSigDenominator = 0;
};

} // namespace acemusic::test
