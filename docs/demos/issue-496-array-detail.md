# #496 — plugin surfaces FastAPI array-shaped 422 detail

*2026-09-18T20:32:14Z*

The plugin's real PlatformClient (compiled into a console harness) posts an invalid payload to the real platform API (uvicorn :8796, local Mongo). Token is minted for a throwaway free user; only its fingerprint is shown.

```bash
sha256sum /home/frankbria/.claude/jobs/ab7e2d56/tmp/token | cut -c1-12
```

```output
47d5565af342
```

AC1 — what the live platform actually returns for a 422: detail is a list of {loc, msg, type}.

```bash
curl -s -X POST localhost:8796/api/v1/generate -H "Authorization: Bearer $(cat /home/frankbria/.claude/jobs/ab7e2d56/tmp/token)" -H 'Content-Type: application/json' -d '{"duration":"not-a-number"}' -w '\nHTTP %{http_code}\n' | python3 -c 'import sys;b=sys.stdin.read();print(b)' | cut -c1-400
```

```output
{"detail":[{"type":"missing","loc":["body","prompt"],"msg":"Field required","input":{"duration":"not-a-number"}},{"type":"float_parsing","loc":["body","duration"],"msg":"Input should be a valid number, unable to parse string as a number","input":"not-a-number"}]}
HTTP 422

```

Before (main's PlatformClient.cpp): the musician sees only the bare status.

```bash
/home/frankbria/.claude/jobs/ab7e2d56/tmp/harness/build/Harness496Before_artefacts/Release/Harness496Before http://localhost:8796 $(cat /home/frankbria/.claude/jobs/ab7e2d56/tmp/token) '{"duration":"not-a-number"}'
```

```output
ok=0
errorMessage=Server returned HTTP 422
```

After (this branch): the first element's msg, with its loc.

```bash
/home/frankbria/.claude/jobs/ab7e2d56/tmp/harness/build/Harness496_artefacts/Release/Harness496 http://localhost:8796 $(cat /home/frankbria/.claude/jobs/ab7e2d56/tmp/token) '{"duration":"not-a-number"}'
```

```output
ok=0
errorMessage=Field required (body.prompt)
```

Regression: a string-shaped detail still comes through unchanged (live 401 with a bad token).

```bash
/home/frankbria/.claude/jobs/ab7e2d56/tmp/harness/build/Harness496_artefacts/Release/Harness496 http://localhost:8796 bogus-token '{"prompt":"x"}'
```

```output
ok=0
errorMessage=Invalid access token.
```

AC2 — VoiceGenerationTests.cpp covers the array shape alongside the 402/403 cases; full plugin suite:

```bash
grep -E 'validation error names|tier refusal|running out of credits' plugin/build/Testing/Temporary/LastTest.log | grep Completed; grep -c FAILED plugin/build/Testing/Temporary/LastTest.log; tail -1 /home/frankbria/.claude/jobs/ab7e2d56/tmp/ctest.log
```

```output
Completed tests in VoiceGeneration / the tier refusal reaches the musician instead of a bare status code
Completed tests in VoiceGeneration / running out of credits says so, with the numbers
Completed tests in VoiceGeneration / a validation error names the field the platform rejected
0
Total Test time (real) =  51.54 sec
```
