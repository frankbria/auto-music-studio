# Issue #71 — US-8.3: OAuth2 authentication and JWT tokens

**Status**: awaiting plan approval
**Branch**: (Phase 5) `feature/us-8-3-oauth-jwt-auth`
**Plan source**: CodeRabbit comment, adapted to current codebase

## Adapted Plan

### Step 1 — Dependencies + settings
- `pyproject.toml`: add `authlib>=1.3`, `pyjwt>=2.8`; dev: `freezegun`; run `uv lock` + `uv sync`
- Extend `ApiSettings` in `src/acemusic/api/settings.py` (NOT a new config.py — follow existing pattern, `ACEMUSIC_API_` prefix):
  - `google_client_id`, `google_client_secret`, `google_redirect_uri`
  - `discord_client_id`, `discord_client_secret`, `discord_redirect_uri`
  - `jwt_secret_key: str | None = None` (runtime check raises clear error when auth used unconfigured), `jwt_algorithm="HS256"`, `access_token_expire_minutes=15`, `refresh_token_expire_days=7`
- Update `.env.example` with new vars

### Step 2 — Data models (tests: `tests/test_auth_models.py`, `@pytest.mark.integration`, real MongoDB via `mongo_db` fixture)
- `src/acemusic/api/models/user.py`: add `subscription_tier: str = "free"`; add compound unique **partial** index on `(oauth_provider, oauth_id)` (partialFilterExpression — fields are nullable, plain unique index would collide on nulls)
- New `src/acemusic/api/models/refresh_token.py`: `RefreshToken` document — `token_hash` (str, unique index; store SHA-256 of token, never raw), `user_id` (PydanticObjectId, indexed), `expires_at` (TTL index, expireAfterSeconds=0), `revoked: bool = False`, `created_at`
- Register in `ALL_MODELS` (`src/acemusic/api/models/__init__.py`)

### Step 3 — JWT token utilities (tests: `tests/test_auth_tokens.py`, unit, freezegun for expiry)
- `src/acemusic/api/auth/tokens.py`:
  - `create_access_token(user_id, email, subscription_tier)` → JWT `{"sub", "email", "tier", "exp", "type": "access"}`, 15-min expiry
  - `create_refresh_token()` → `secrets.token_urlsafe` opaque string
  - `decode_access_token(token)` → payload dict; raises on expired/invalid signature/wrong type

### Step 4 — Refresh token service (tests: `tests/test_auth_services.py`, `@pytest.mark.integration`, real MongoDB — NO Beanie mocks per project no-mocking rule)
- `src/acemusic/api/auth/services.py`: `store_refresh_token`, `validate_refresh_token` (returns user_id or None; checks revoked + expiry), `revoke_refresh_token`, `revoke_all_user_tokens` — all operate on hashes

### Step 5 — OAuth2 clients ✅ (also unit-tested directly in tests/test_auth_oauth.py)
- `src/acemusic/api/auth/oauth.py`: authlib clients — Google via OIDC discovery (`openid email profile`), Discord explicit endpoints (`identify email`)
- `get_authorization_url(provider)` / `exchange_code_for_user(provider, code)` abstracting differences
- CSRF `state`: short-lived signed JWT (stateless — no session middleware in app)

### Step 6 — Auth dependency ✅ (tests: `tests/test_auth_dependencies.py`)
- `src/acemusic/api/auth/dependencies.py`: `get_current_user` (HTTPBearer, 401 on missing/expired/invalid) → `CurrentUser(user_id, email, subscription_tier)`; `get_current_user_optional`

### Step 7 — Auth router + registration ✅ (tests: `tests/test_auth_routes.py`, httpx.AsyncClient over ASGITransport, mocked OAuth provider exchange only)
- `src/acemusic/api/routers/auth.py`: `POST /login/{provider}` (400 invalid provider), `POST /callback/{provider}` (upsert User, issue tokens), `POST /refresh` (401 invalid/revoked; rotate refresh token), `POST /logout` (204)
- Register in `src/acemusic/api/main.py` under `/api/v1/auth`; `/api/v1/health` stays unprotected
- Route-protection test proves a router with `Depends(get_current_user)` returns 401 without/with-expired token, 200 with valid token (no workspaces/clips routers exist yet — pattern documented for future routers)

## Acceptance Criteria
- [x] Google OAuth login returns a valid JWT on success
      → `test_auth_routes.py::TestCallback::test_google_callback_creates_user_and_returns_jwt`
- [x] Discord OAuth login returns a valid JWT on success
      → `test_auth_routes.py::TestCallback::test_discord_callback_creates_user_and_returns_jwt`
- [x] Expired access tokens return 401; refresh token exchange returns a new access token
      → `test_auth_routes.py::TestRouteProtectionPattern::test_expired_token_401`
        + `test_auth_routes.py::TestRefresh::test_refresh_rotates_and_old_token_revoked`
- [x] Invalid or revoked refresh tokens return 401
      → `test_auth_routes.py::TestRefresh::test_refresh_invalid_token_401`
        + `::test_refresh_revoked_token_401`
- [x] All `/api/v1/` routes (except health, auth) return 401 without a Bearer token
      → `test_auth_routes.py::TestRouteProtectionPattern::test_no_token_401`
        + `::test_valid_token_200` + `::test_health_stays_unprotected`

## Deviations from CodeRabbit plan (with reasoning)
1. **Extend `settings.py`/`ApiSettings`** instead of new `config.py`/`AuthSettings` singleton — codebase already has this pattern with `ACEMUSIC_API_` env prefix (plan predates US-8.1 landing)
2. **PyJWT instead of python-jose** — python-jose is unmaintained with known CVEs; PyJWT is the maintained standard
3. **Drop `passlib[bcrypt]`** — YAGNI; no password auth in this issue
4. **Hash refresh tokens (SHA-256) before storage** — raw tokens in DB are a credential-leak risk
5. **Partial unique index** on `(oauth_provider, oauth_id)` — fields are nullable on existing User model
6. **Service tests use real MongoDB** (existing `mongo_db` fixture) — project no-mocking rule; only external OAuth provider HTTP is mocked
7. **Signed-JWT `state` param** for CSRF — app has no session middleware; stateless validation
8. **User model needs only `subscription_tier`** — `oauth_provider`/`oauth_id`/`email`(unique)/timestamps already exist
