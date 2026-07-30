#include "GenerationRequest.h"

namespace acemusic
{

int GenerationRequest::inferenceStepsFor (Quality quality) noexcept
{
    // src/acemusic/client.py documents "Turbo: 8, Standard: 32-64" for
    // inference_steps; High extends the same curve.
    switch (quality)
    {
        case Quality::turbo:     return 8;
        case Quality::standard:  return 48;
        case Quality::high:      return 120;
    }

    return 48;
}

juce::String GenerationRequest::toString (Quality quality) noexcept
{
    switch (quality)
    {
        case Quality::turbo:     return "Turbo";
        case Quality::standard:  return "Standard";
        case Quality::high:      return "High";
    }

    return "Standard";
}

juce::String GenerationRequest::toString (Mode mode) noexcept
{
    switch (mode)
    {
        case Mode::textToMusic:  return "Text to Music";
        case Mode::cover:        return "Cover";
    }

    return "Text to Music";
}

juce::Array<GenerationRequest::Quality> GenerationRequest::allQualities()
{
    return { Quality::turbo, Quality::standard, Quality::high };
}

juce::StringArray GenerationRequest::vocalLanguages()
{
    // Sent as display names — `web/lib/generate.ts` posts vocal_language:"English",
    // so the plugin matches rather than introducing codes the server has not seen.
    return { "Arabic", "Bengali", "Bulgarian", "Catalan", "Chinese (Cantonese)",
             "Chinese (Mandarin)", "Croatian", "Czech", "Danish", "Dutch",
             "English", "Estonian", "Filipino", "Finnish", "French",
             "German", "Greek", "Gujarati", "Hebrew", "Hindi",
             "Hungarian", "Icelandic", "Indonesian", "Italian", "Japanese",
             "Kannada", "Korean", "Latvian", "Lithuanian", "Malay",
             "Malayalam", "Marathi", "Norwegian", "Persian", "Polish",
             "Portuguese", "Punjabi", "Romanian", "Russian", "Serbian",
             "Slovak", "Slovenian", "Spanish", "Swahili", "Swedish",
             "Tamil", "Telugu", "Thai", "Turkish", "Ukrainian",
             "Urdu", "Vietnamese", "Welsh", "Yoruba", "Zulu" };
}

juce::StringArray GenerationRequest::musicalKeys()
{
    juce::StringArray keys { "Any" };

    for (const auto* tonic : { "C", "C#", "D", "D#", "E", "F",
                               "F#", "G", "G#", "A", "A#", "B" })
    {
        keys.add (juce::String (tonic) + " major");
        keys.add (juce::String (tonic) + " minor");
    }

    return keys;
}

juce::String GenerationRequest::findProblem() const
{
    if (prompt.trim().isEmpty())
        return "Enter a prompt describing the music you want";

    if (durationSeconds <= 0)
        return "Duration must be greater than zero";

    if (mode == Mode::cover && sourceAudioPath.trim().isEmpty())
        return "Cover mode needs a source audio file";

    return {};
}

juce::var GenerationRequest::toPayload() const
{
    auto* payload = new juce::DynamicObject();

    payload->setProperty ("prompt", prompt.trim());
    payload->setProperty ("batch_size", clipCount);
    payload->setProperty ("audio_format", "wav");
    payload->setProperty ("audio_duration", durationSeconds);
    payload->setProperty ("inference_steps", inferenceStepsFor (quality));

    // Optional fields are omitted, not sent empty: the server reads an absent key as
    // "you choose", where "" or -1 would be taken literally.
    if (lyrics.trim().isNotEmpty())
        payload->setProperty ("lyrics", lyrics);

    if (vocalLanguage.isNotEmpty())
        payload->setProperty ("vocal_language", vocalLanguage);

    if (instrumental)
        payload->setProperty ("instrumental", true);

    if (bpm > 0)
        payload->setProperty ("bpm", bpm);

    if (key.isNotEmpty())
        payload->setProperty ("key", key);

    if (seed >= 0)
        payload->setProperty ("seed", seed);

    if (model.isNotEmpty())
        payload->setProperty ("model", model);

    // text2music is the server's default; the Python client omits it for exactly
    // this reason, so sending it would be a behaviour change rather than a no-op.
    if (mode == Mode::cover)
    {
        payload->setProperty ("task_type", "cover");
        payload->setProperty ("src_audio_path", sourceAudioPath.trim());
    }

    return juce::var (payload);
}

juce::String GenerationRequest::toPayloadJson() const
{
    return juce::JSON::toString (toPayload(), true);
}

} // namespace acemusic
