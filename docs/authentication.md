# Authentication and frontend integration

Use Supabase Auth in the separately developed v0/Next.js frontend. The API does
not implement passwords, registration, refresh tokens, or a production token
issuer. A Next.js backend-for-frontend should keep Supabase sessions in secure
HTTP-only cookies and forward the access token as `Authorization: Bearer <token>`
when calling FastAPI. Use Supabase's maintained SSR integration and configure
CSRF protections on cookie-authenticated frontend server actions. Never put the
service role key, encryption key, or development signing key into `NEXT_PUBLIC_*`.

The backend pins the project's issuer (`SUPABASE_URL/auth/v1`), audience
(`authenticated` by default), and algorithms (ES256/RS256). It obtains public keys
from that project's `/.well-known/jwks.json`, verifies signature, expiry, issuance,
maximum lifetime, subject UUID, and session UUID, and checks confirmed email via
the provider-owned `/auth/v1/user` response. Arbitrary `user_metadata` and JWT role
claims cannot grant company permissions. PostgreSQL stores account status,
membership, signatory, verifier, operator, and research authorization.

JWKS caching is bounded to five minutes in this process, in addition to Supabase's
edge cache. On signing-key incidents, stop exposed API processes and clear provider
caches following Supabase's key-rotation procedure. `clear_jwks_cache()` clears
this application's cache. Local session revocations are checked by the API on
every request; provider logout/refresh-token revocation and existing access token
expiry have distinct lifetimes. Use a short Supabase access-token lifetime and
route application logout through the backend as well as Supabase.

For development only, explicitly set `ENVIRONMENT=development`, `AUTH_MODE=local`,
`ALLOW_DEV_AUTH=true`, and a random `DEV_JWT_SECRET` of at least 32 characters.
`mint_dev_token` is a CLI fixture helper for fictional accounts with database
permissions. It is not exposed as a login endpoint. Production/staging settings
reject this mode, and development requests should be loopback-only.

For each API write, send an `Idempotency-Key` unique to the intended operation.
Retries of the same operation reuse it; changing the payload with the same key is
a conflict. Versioned resources require their current version or `If-Match`
according to the generated OpenAPI request schema. Read membership permissions
from `/v1/sessions/me`; client page guards improve navigation but cannot authorize
backend access. Do not treat email domain or a frontend-selected role as hiring
authority.

Provider integration has unit coverage with cryptographically signed tokens and
mocked remote responses. Live Supabase login, project configuration, email,
storage, and Vercel cookie behavior require the user's actual project credentials
and frontend source before deployment verification can be completed.

