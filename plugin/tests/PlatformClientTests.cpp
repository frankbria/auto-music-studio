#include "PlatformClient.h"
#include "StubAceStepServer.h"

namespace acemusic
{

/** The platform half of clip sync (US-24.5), driven against a stub HTTP server.

    There is no deployed platform reachable from this environment, so these cover the
    request shapes, the parsing, and — the part most likely to regress — what happens
    when the platform is unreachable. */
class PlatformClientTests final : public juce::UnitTest
{
public:
    PlatformClientTests()
        : juce::UnitTest ("PlatformClient", "acemusic")
    {
    }

    struct ScopedTempDir
    {
        ScopedTempDir()
        {
            directory = juce::File::getSpecialLocation (juce::File::tempDirectory)
                            .getChildFile ("acemusic-platform-"
                                           + juce::String (juce::Random::getSystemRandom().nextInt (1 << 30)));
            directory.createDirectory();
        }

        ~ScopedTempDir()    { directory.deleteRecursively(); }

        juce::File directory;
    };

    void runTest() override
    {
        beginTest ("a URL with no scheme, or a forged key, is refused before any request");
        {
            expect (Platform::findUrlProblem ("").isNotEmpty(), "an empty URL was accepted");

            // Nothing is sent for an unusable base URL — the client must not reach the
            // socket to discover a typo.
            const auto result = Platform::listWorkspaces ("", "key");
            expect (! result.ok);
            expect (result.errorMessage.isNotEmpty());

            // A control character in the key would terminate the Authorization header
            // and let another be injected. Shared with AceStepClient via HttpSupport.
            test::StubAceStepServer server;
            expect (server.start() != 0);

            const auto forged = Platform::listWorkspaces (server.getBaseUrl(), "abc\r\nX-Evil: 1");
            expect (! forged.ok, "a key containing CRLF was sent");
            expect (forged.errorMessage.containsIgnoreCase ("invalid"),
                    "unexpected message: " + forged.errorMessage);
            expectEquals (server.getRequestCountFor ("/api/v1/workspaces"), 0,
                          "a request went out despite the forged key");
        }

        beginTest ("AC: workspaces are listed from the platform");
        {
            test::StubAceStepServer server;
            expect (server.start() != 0);
            server.setResponseFor ("/workspaces",
                                   R"({"workspaces":[{"id":"w1","name":"Demos"},{"id":"w2","name":"Album"}]})");

            const auto result = Platform::listWorkspaces (server.getBaseUrl(), "token");

            expect (result.ok, result.errorMessage);
            expectEquals (result.workspaces.size(), 2);
            expectEquals (result.workspaces[0].id, juce::String ("w1"));
            expectEquals (result.workspaces[0].name, juce::String ("Demos"));
            expectEquals (result.workspaces[1].name, juce::String ("Album"));

            // The path the real API actually serves.
            expect (server.getRequestCountFor ("/api/v1/workspaces") > 0,
                    "hit the wrong path: " + server.getLastPath());
        }

        beginTest ("AC: clips are listed, with search and workspace filters escaped");
        {
            test::StubAceStepServer server;
            expect (server.start() != 0);
            server.setResponseFor ("/clips",
                                   R"({"clips":[{"id":"c1","title":"Dub","format":"wav","duration":32.5,
                                       "bpm":118,"key":"C minor","style_tags":["dub","bass"],
                                       "created_at":"2026-01-01T00:00:00Z"}],"total":1})");

            const auto result = Platform::listClips (server.getBaseUrl(), "token", "w1", "dub & bass");

            expect (result.ok, result.errorMessage);
            expectEquals (result.clips.size(), 1);
            expectEquals (result.clips[0].id, juce::String ("c1"));
            expectEquals (result.clips[0].title, juce::String ("Dub"));
            expectEquals (result.clips[0].bpm, 118);
            expectEquals (result.clips[0].key, juce::String ("C minor"));
            expectWithinAbsoluteError (result.clips[0].duration, 32.5, 1.0e-9);
            expectEquals (result.clips[0].styleTags.size(), 2);
            expectEquals (result.total, 1);

            // The ampersand in the search must be escaped, or it injects a parameter.
            const auto path = server.getLastPath();
            expect (! path.contains ("dub & bass"), "the search term was not escaped: " + path);
            expect (path.contains ("workspace_id=w1"), "the workspace filter was dropped: " + path);
            expect (path.contains ("search="), "the search was dropped: " + path);
        }

        beginTest ("AC: importing a clip writes the audio to disk");
        {
            ScopedTempDir dir;
            test::StubAceStepServer server;
            expect (server.start() != 0);
            server.setResponseFor ("/audio", "RIFF....WAVEfmt fake audio payload");

            const auto destination = dir.directory.getChildFile ("imported").getChildFile ("clip.wav");
            const auto result = Platform::downloadClip (server.getBaseUrl(), "token", "c1", destination);

            expect (result.ok, result.errorMessage);
            expect (destination.existsAsFile(), "no file was written");
            expect (destination.getSize() > 0);
            expectEquals (result.file.getFullPathName(), destination.getFullPathName());

            // Nothing partial is left behind.
            expect (! destination.getSiblingFile (destination.getFileName() + ".partial").existsAsFile(),
                    "a .partial file survived a successful download");
        }

        beginTest ("an empty download is an error, not a zero-byte clip");
        {
            ScopedTempDir dir;
            test::StubAceStepServer server;
            expect (server.start() != 0);
            server.setResponseFor ("/audio", "");

            const auto destination = dir.directory.getChildFile ("empty.wav");
            const auto result = Platform::downloadClip (server.getBaseUrl(), "token", "c1", destination);

            expect (! result.ok, "an empty body was accepted as a clip");
            expect (! destination.existsAsFile(), "a zero-byte clip was left on disk");
        }

        beginTest ("AC: pushing a clip posts it and reports the new id");
        {
            ScopedTempDir dir;
            test::StubAceStepServer server;
            expect (server.start() != 0);
            server.setResponseFor ("/clips/upload", R"({"id":"new-clip-1","title":"Bass layer"})");

            const auto audio = dir.directory.getChildFile ("layer.wav");
            audio.replaceWithData ("RIFF....WAVEfmt payload", 23);

            const auto result = Platform::uploadClip (server.getBaseUrl(), "token", "w1",
                                                      audio, "Bass layer", 120, "C minor", 16.0);

            expect (result.ok, result.errorMessage);
            expectEquals (result.clipId, juce::String ("new-clip-1"));

            // The metadata really went with it.
            const auto body = server.getBodyFor ("/api/v1/clips/upload");
            expect (body.contains ("Bass layer"), "the title was not sent");
            expect (body.contains ("w1"), "the workspace was not sent");
            expect (body.contains ("120"), "the bpm was not sent");
        }

        beginTest ("pushing without a workspace, or of a missing file, is refused locally");
        {
            ScopedTempDir dir;
            test::StubAceStepServer server;
            expect (server.start() != 0);

            const auto audio = dir.directory.getChildFile ("layer.wav");
            audio.replaceWithData ("RIFF....WAVEfmt payload", 23);

            const auto noWorkspace = Platform::uploadClip (server.getBaseUrl(), "token", "", audio, "t", 0, "", 0.0);
            expect (! noWorkspace.ok, "pushed with no workspace chosen");
            expect (noWorkspace.errorMessage.containsIgnoreCase ("workspace"));

            const auto missing = dir.directory.getChildFile ("gone.wav");
            const auto noFile = Platform::uploadClip (server.getBaseUrl(), "token", "w1", missing, "t", 0, "", 0.0);
            expect (! noFile.ok, "pushed a file that is not there");

            expectEquals (server.getRequestCountFor ("/api/v1/clips/upload"), 0,
                          "a doomed upload still went out over the network");
        }

        beginTest ("a rejected key says so, rather than reporting a bare status");
        {
            test::StubAceStepServer server;
            expect (server.start() != 0);
            server.setStatusLine ("HTTP/1.1 401 Unauthorized");

            const auto result = Platform::listWorkspaces (server.getBaseUrl(), "wrong-token");

            expect (! result.ok);
            expect (result.errorMessage.containsIgnoreCase ("key"),
                    "unhelpful message: " + result.errorMessage);
        }

        beginTest ("AC: an unreachable platform reports it, and reports it usably");
        {
            // The one that matters for "connection errors do not affect local
            // generation": every entry point has to fail cleanly and quickly.
            juce::String deadUrl;
            {
                test::StubAceStepServer server;
                expect (server.start() != 0);
                deadUrl = server.getBaseUrl();
            }   // stopped

            ScopedTempDir dir;
            const auto start = juce::Time::getMillisecondCounter();

            const auto workspaces = Platform::listWorkspaces (deadUrl, "token", nullptr, 2000);
            const auto clips = Platform::listClips (deadUrl, "token", "", "", 1, 20, nullptr, 2000);
            const auto download = Platform::downloadClip (deadUrl, "token", "c1",
                                                          dir.directory.getChildFile ("x.wav"), nullptr, 2000);

            const auto elapsed = juce::Time::getMillisecondCounter() - start;

            for (const auto* result : { &workspaces, &clips, &download })
            {
                expect (! result->ok, "a dead platform reported success");
                expect (! result->cancelled, "a dead platform reported as cancelled");
                expect (result->errorMessage.isNotEmpty(), "failed with no reason given");
                // "HTTP 0" is what curl produces here and is not actionable.
                expect (! result->errorMessage.contains ("HTTP 0"),
                        "unactionable message: " + result->errorMessage);
            }

            expect (elapsed < 20000, "a dead platform took " + juce::String ((int) elapsed) + "ms to give up");
            expect (! dir.directory.getChildFile ("x.wav").existsAsFile(),
                    "a failed download left a file behind");
        }

        beginTest ("a cancelled call reports cancelled, not an error");
        {
            test::StubAceStepServer server;
            expect (server.start() != 0);

            const auto result = Platform::listWorkspaces (server.getBaseUrl(), "token",
                                                          [] { return true; });

            expect (! result.ok);
            expect (result.cancelled, "a cancellation was reported as a failure");
            // A cancel must not surface as an error the user sees.
            expect (result.errorMessage.isEmpty(), "cancelling produced an error message");
        }

        beginTest ("a body that is not the expected shape is an error, not a crash");
        {
            test::StubAceStepServer server;
            expect (server.start() != 0);
            server.setResponseFor ("/workspaces", "not json at all");

            const auto result = Platform::listWorkspaces (server.getBaseUrl(), "token");
            expect (! result.ok, "garbage parsed as a workspace list");
            expect (result.errorMessage.isNotEmpty());

            server.setResponseFor ("/clips", R"({"unexpected":"shape"})");
            const auto clips = Platform::listClips (server.getBaseUrl(), "token", "", "");
            expect (! clips.ok, "an unexpected shape parsed as a clip list");
        }
    }
};

static PlatformClientTests platformClientTests;

} // namespace acemusic
