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

        return info;
    }

    bool reportsPosition = true;

    /** <= 0 means "the host publishes no tempo". */
    double bpm = 120.0;

    /** < 0 means "the host publishes no position". */
    double timeInSeconds = 0.0;
};

} // namespace acemusic::test
