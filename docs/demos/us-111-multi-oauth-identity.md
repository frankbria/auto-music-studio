# #111 — Multiple OAuth identities per account

Run against a real MongoDB. The HTTP layer is covered by the integration tests in
`tests/test_auth_routes.py`, which drive the actual FastAPI callback with a stubbed
provider exchange; this exercises the service the callback calls.

Full transcript: `uv run python scripts/demo_us_111.py`

---

## 1. A new account records the identity it was created with

```
sign in with Google -> email=musician@example.com primary=google identities=[google:g-123]
```

## 2. The same email via Discord links, instead of being refused

This was a `409` before. Deterministic and safe — no duplicate accounts, no 500 on the
unique index — but it meant someone with the same address on both providers could only
ever use whichever they happened to sign up with.

```
sign in with Discord -> primary=google identities=[google:g-123, discord:d-456]
same account?           True
accounts for that email: 1

...and either provider now signs into it:
  google   -> id=9b0f9b  (same: True)
  discord  -> id=9b0f9b  (same: True)
```

`primary` stays `google`. The legacy `oauth_provider`/`oauth_id` pair is the
denormalisation the existing partial-unique index is built on, so a link must not repoint
it — that would move the account out from under the index entry already guarding it.

At the HTTP layer the same thing, asserted in
`test_same_email_via_second_provider_links_to_one_account`: two callbacks, two providers,
both `200`, and both access tokens carry the same `sub`.

## 3. An unverified collision is still refused

```
EmailAlreadyRegisteredError: musician@example.com  -> the route maps this to 409
```

Linking hands a provider control of an existing account, so it is gated on the provider
having verified the address. `email_verified` defaults to **False** in the service: every
caller that has not thought about verification keeps the old refusal, and only the OAuth
callback opts in — having already turned unverified addresses into a `403` one step
earlier (`test_an_unverified_second_provider_never_reaches_the_link`).

## 4. An account written before this change

The interesting case, because it is the one a migration would normally be for. This
document is inserted through the raw collection with no `identities` key at all — exactly
the on-disk shape of a pre-#111 user:

```
on disk before login: identities key present = False
signs in fine       -> primary=google identities=[google:g-legacy]
on disk after login : identities = [{'provider': 'google', 'oauth_id': 'g-legacy', 'linked_at': None}]
and links a second  -> identities=[google:g-legacy, discord:d-legacy]
```

Materialised by a `model_validator(mode="before")` on read, then persisted by a conditional
update gated on the field still being absent — the `credits_reset_at` backfill idiom, and
for the same reason: writing only the field being backfilled cannot revert a concurrent
write the way a whole-document `save()` can.

So there is no batch migration, and no window where an existing user is locked out.

## 5. Concurrent logins converge

```
6 concurrent Discord logins -> distinct accounts: 1
identities recorded         -> 2 (no duplicate entries)
```

The link is a single `$push` filtered on the identity not already being present, so six
racing logins append one entry between them rather than six.

## 6. An identity still cannot be claimed by two accounts

```
oauth_provider_1_oauth_id_1        : key=[('oauth_provider',1),('oauth_id',1)]           unique=True
identities_provider_oauth_id_unique: key=[('identities.provider',1),('identities.oauth_id',1)] unique=True
rejected: DuplicateKeyError
```

Both indexes exist, and the new one is **additive** — nothing was redefined. That is
deliberate: Beanie creates indexes at startup but never rebuilds one whose spec changed, so
redefining an index is a silent no-op on any database where it already exists. A test
database (dropped per run) would never show that; a production cluster would.

---

## The trust boundary, stated plainly

This treats "the provider says the email is verified" as proof of the same human. It is the
industry-standard trade and it is what the issue asks for, but it is a real transfer:
Discord's `verified` means Discord confirmed the address, and Discord lets users change
their email. Anyone who can get a supported provider to verify a victim's address can link
into that account.

Mitigated, not eliminated, by requiring verification and recording `linked_at` provenance.
The stronger alternative — requiring an authenticated session before a second provider can
be attached — is a different user experience than the issue specifies, so it is flagged
rather than silently substituted.

## Not covered here

- **No unlink.** Nothing removes an identity yet; the issue does not ask for it, and a
  half-built unlink that can strand an account with zero identities would be worse than
  none.
- **The API does not report which providers are linked.** `UserProfileResponse` maps fields
  explicitly and deliberately never exposed `oauth_*`; adding a "signed in with" surface is
  a UI story, not this one.
