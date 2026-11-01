# #613 A clock stepped backwards no longer 401s a fresh session

*2026-11-01*

**Root cause.** The load-only 401 was `"Invalid access token."`, and PyJWT's message behind it was `The token is not yet valid (iat)`. `decode_access_token` called `jwt.decode` with no leeway. When the clock steps backwards (WSL2 resyncs under load; skewed API instances in production), a token minted a moment earlier reads as issued in the future.

**Reproduced deterministically.** Before the fix, this test failed with exactly that error:

```output
E           jwt.exceptions.ImmatureSignatureError: The token is not yet valid (iat)
E           acemusic.api.auth.tokens.TokenInvalidError: Invalid access token: The token is not yet valid (iat)
```

**Fix.** `jwt.decode(..., leeway=CLOCK_SKEW_LEEWAY)`, set to 10 seconds. With it:

```output
tests/test_auth_tokens.py::TestClockSkew::test_a_token_stamped_a_few_seconds_ahead_still_decodes PASSED
tests/test_auth_tokens.py::TestClockSkew::test_a_token_stamped_well_into_the_future_is_still_invalid PASSED
```

**Under load.** `TestClipMetadataScreening`, the class with the original flake, passed 20 runs out of 20 while other suites ran against the same mongod. The five tests #621 lists as load-only flakes passed 15 runs out of 15 under the same conditions:

```output
TestClipMetadataScreening: passes=20 fails=0 (13 passed per run)
#621's five tests:         passes=15 fails=0 (12 passed per run)
```

The once-flaky assertion now prints `resp.text` on failure, so if anything else ever shows up there, its detail will be visible.
