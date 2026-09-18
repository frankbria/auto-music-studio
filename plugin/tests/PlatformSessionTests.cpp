#include "PlatformSession.h"
#include "StubAceStepServer.h"

#if JUCE_LINUX || JUCE_MAC || JUCE_BSD
 #include <sys/stat.h>
#endif

namespace acemusic
{

/** Keeping the platform session alive past the access token's 15 minutes (#445).

    Driven against the stub in its `requireBearer` mode, so the 401 -> refresh -> retry
    sequence is real HTTP, not a simulated status. */
class PlatformSessionTests final : public juce::UnitTest
{
public:
    PlatformSessionTests()
        : juce::UnitTest ("PlatformSession", "acemusic")
    {
    }

    struct ScopedTokenFile
    {
        ScopedTokenFile()
        {
            directory = juce::File::getSpecialLocation (juce::File::tempDirectory)
                            .getChildFile ("acemusic-session-"
                                           + juce::String (juce::Random::getSystemRandom().nextInt (1 << 30)));
            directory.createDirectory();
        }

        ~ScopedTokenFile()                   { directory.deleteRecursively(); }

        juce::File file() const              { return directory.getChildFile ("platform.token"); }

        juce::File directory;
    };

    /** Collects everything JUCE logs while it is installed. */
    struct CapturingLogger final : juce::Logger
    {
        CapturingLogger()                    { juce::Logger::setCurrentLogger (this); }
        ~CapturingLogger() override          { juce::Logger::setCurrentLogger (nullptr); }
        void logMessage (const juce::String& message) override    { logged << message << "\n"; }

        juce::String logged;
    };

    static constexpr const char* rotated =
        R"({"access_token":"access-2","refresh_token":"refresh-2","token_type":"bearer","expires_in":900})";

    static Platform::Result listWorkspaces (Platform::Session& session, const juce::String& url)
    {
        return session.run (url, [&] (const juce::String& access)
        {
            return Platform::listWorkspaces (url, access);
        });
    }

    void runTest() override
    {
        beginTest ("AC: an expired access token is refreshed and the call retried, unseen");
        {
            ScopedTokenFile tokens;
            test::StubAceStepServer server;
            expect (server.start() != 0);
            server.setResponseFor ("/api/v1/workspaces", R"([{"id":"w1","name":"Demos"}])");
            server.setResponseFor ("/api/v1/auth/refresh", rotated);
            server.requireBearer ("access-2");

            Platform::Session session (tokens.file());
            session.setRefreshToken ("refresh-1");

            CapturingLogger logger;
            const auto result = listWorkspaces (session, server.getBaseUrl());

            expect (result.ok, "the call was not retried: " + result.errorMessage);
            expectEquals (result.workspaces.size(), 1);
            expectEquals (server.getRequestCountFor ("/api/v1/auth/refresh"), 1);
            expect (server.getBodyFor ("/api/v1/auth/refresh").contains ("\"refresh-1\""),
                    "the stored refresh token was not the one sent");

            // AC: never in a log.
            for (auto* secret : { "refresh-1", "refresh-2", "access-2" })
                expect (! logger.logged.contains (secret), juce::String ("logged a token: ") + secret);

            // A second call reuses the new access token instead of refreshing again.
            expect (listWorkspaces (session, server.getBaseUrl()).ok);
            expectEquals (server.getRequestCountFor ("/api/v1/auth/refresh"), 1);
        }

        beginTest ("AC: the rotated refresh token replaces the old one on disk, at 0600");
        {
            ScopedTokenFile tokens;
            test::StubAceStepServer server;
            expect (server.start() != 0);
            server.setResponseFor ("/api/v1/workspaces", "[]");
            server.setResponseFor ("/api/v1/auth/refresh", rotated);
            server.requireBearer ("access-2");

            {
                Platform::Session session (tokens.file());
                session.setRefreshToken ("refresh-1");
                expect (listWorkspaces (session, server.getBaseUrl()).ok);
            }

            // Single-use tokens: keeping the spent one would fail at the next refresh.
            expectEquals (tokens.file().loadFileAsString(), juce::String ("refresh-2"));
            expectEquals (Platform::Session (tokens.file()).getRefreshToken(), juce::String ("refresh-2"));

           #if JUCE_LINUX || JUCE_MAC || JUCE_BSD
            struct stat info {};
            expectEquals (::stat (tokens.file().getFullPathName().toRawUTF8(), &info), 0);
            expectEquals ((int) (info.st_mode & 0777), 0600, "the token file is readable by others");
           #endif
        }

        beginTest ("AC: a rejected refresh token says so and is tried exactly once");
        {
            ScopedTokenFile tokens;
            test::StubAceStepServer server;
            expect (server.start() != 0);
            server.setStatusFor ("/api/v1/auth/refresh", "HTTP/1.1 401 Unauthorized");
            server.setResponseFor ("/api/v1/auth/refresh", R"({"detail":"Invalid or expired refresh token."})");
            server.requireBearer ("access-never-issued");

            Platform::Session session (tokens.file());
            session.setRefreshToken ("revoked");

            const auto result = listWorkspaces (session, server.getBaseUrl());

            expect (! result.ok);
            expect (result.errorMessage.containsIgnoreCase ("plugin token"),
                    "unexpected message: " + result.errorMessage);
            expectEquals (server.getRequestCountFor ("/api/v1/auth/refresh"), 1);
            expectEquals (server.getRequestCountFor ("/api/v1/workspaces"), 1, "the call was retried anyway");
        }

        beginTest ("a fresh token that is still refused is not refreshed again");
        {
            ScopedTokenFile tokens;
            test::StubAceStepServer server;
            expect (server.start() != 0);
            server.setResponseFor ("/api/v1/auth/refresh", rotated);
            server.requireBearer ("an-access-token-it-will-never-get");

            Platform::Session session (tokens.file());
            session.setRefreshToken ("refresh-1");

            const auto result = listWorkspaces (session, server.getBaseUrl());

            expect (! result.ok);
            expect (result.errorMessage.containsIgnoreCase ("plugin token"),
                    "unexpected message: " + result.errorMessage);
            expectEquals (server.getRequestCountFor ("/api/v1/auth/refresh"), 1);
            expectEquals (server.getRequestCountFor ("/api/v1/workspaces"), 2);
        }

        beginTest ("with no plugin token a 401 asks for one instead of saying 'rejected'");
        {
            ScopedTokenFile tokens;
            test::StubAceStepServer server;
            expect (server.start() != 0);
            server.requireBearer ("anything");

            Platform::Session session (tokens.file());
            const auto result = listWorkspaces (session, server.getBaseUrl());

            expect (! result.ok);
            expect (result.errorMessage.containsIgnoreCase ("needs a plugin token"),
                    "unexpected message: " + result.errorMessage);
            expectEquals (server.getRequestCountFor ("/api/v1/auth/refresh"), 0);
        }

        beginTest ("another plugin instance's rotation is picked up from disk");
        {
            // Two instances in one DAW share the token file. When one rotates, the other's
            // in-memory copy is spent — refreshing with it would fail.
            ScopedTokenFile tokens;
            test::StubAceStepServer server;
            expect (server.start() != 0);
            server.setResponseFor ("/api/v1/workspaces", "[]");
            server.setResponseFor ("/api/v1/auth/refresh", rotated);
            server.requireBearer ("access-2");

            Platform::Session first (tokens.file());
            first.setRefreshToken ("refresh-1");
            Platform::Session second (tokens.file());

            tokens.file().replaceWithText ("refresh-from-elsewhere");
            expect (listWorkspaces (second, server.getBaseUrl()).ok);
            expect (server.getBodyFor ("/api/v1/auth/refresh").contains ("\"refresh-from-elsewhere\""),
                    "refreshed with a stale token");
        }

        beginTest ("concurrent 401s share one refresh");
        {
            ScopedTokenFile tokens;
            test::StubAceStepServer server;
            expect (server.start() != 0);
            server.setResponseFor ("/api/v1/workspaces", "[]");
            server.setResponseFor ("/api/v1/auth/refresh", rotated);
            server.requireBearer ("access-2");

            Platform::Session session (tokens.file());
            session.setRefreshToken ("refresh-1");

            std::atomic<int> succeeded { 0 };
            juce::ThreadPool pool (4);

            for (int i = 0; i < 4; ++i)
                pool.addJob ([&] { if (listWorkspaces (session, server.getBaseUrl()).ok) ++succeeded; });

            for (int waited = 0; pool.getNumJobs() > 0 && waited < 20000; waited += 50)
                juce::Thread::sleep (50);

            expectEquals (succeeded.load(), 4);
            // Rotation is single-use: a second refresh with refresh-1 would have been refused.
            expectEquals (server.getRequestCountFor ("/api/v1/auth/refresh"), 1);
        }

        beginTest ("a stopping queue does not start a refresh");
        {
            // Teardown: the refresh holds a process-wide lock across a network call, so
            // one that starts while the plugin is closing would stall every other instance.
            ScopedTokenFile tokens;
            test::StubAceStepServer server;
            expect (server.start() != 0);
            server.setResponseFor ("/api/v1/auth/refresh", rotated);
            server.requireBearer ("access-2");

            Platform::Session session (tokens.file());
            session.setRefreshToken ("refresh-1");

            std::atomic<bool> stopping { false };
            const auto result = session.run (server.getBaseUrl(), [&] (const juce::String& access)
            {
                auto r = Platform::listWorkspaces (server.getBaseUrl(), access);
                stopping = true;   // the host closes the plugin while this call is out
                return r;
            }, [&] { return stopping.load(); });

            expect (result.cancelled, "a stopped run did not report cancelled");
            expectEquals (server.getRequestCountFor ("/api/v1/auth/refresh"), 0);
            expectEquals (session.getRefreshToken(), juce::String ("refresh-1"), "the token was spent anyway");
        }

        beginTest ("pasting a token forgets the old access token and persists the new one");
        {
            ScopedTokenFile tokens;
            Platform::Session session (tokens.file());
            session.setRefreshToken ("  pasted\n");

            expectEquals (session.getRefreshToken(), juce::String ("pasted"));
            expectEquals (tokens.file().loadFileAsString(), juce::String ("pasted"));

            session.setRefreshToken ({});
            expect (! tokens.file().exists(), "clearing the token left it on disk");
        }
    }
};

static PlatformSessionTests platformSessionTests;

} // namespace acemusic
