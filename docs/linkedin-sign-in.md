# LinkedIn sign-in

Career Kitchen uses Supabase's `linkedin_oidc` provider. The email/password form
continues to work independently. The LinkedIn button becomes available only when
the project's public Auth settings report that this provider is enabled; a
provider outage or incomplete setup leaves an explanatory message and email
sign-in available.

## Configure the provider

1. Create or select the Career Kitchen app in the
   [LinkedIn Developer dashboard](https://www.linkedin.com/developers/apps).
   Creating an app requires a LinkedIn Page and app logo.
2. Request the **Sign In with LinkedIn using OpenID Connect** product. Confirm
   that `openid`, `profile`, and `email` scopes are available.
3. Add the Supabase callback URL to the LinkedIn app's authorized redirect URLs:
   `https://<project-ref>.supabase.co/auth/v1/callback`.
4. In Supabase **Authentication → Sign In / Providers → LinkedIn (OIDC)**,
   enter the app's Client ID and Client Secret, enable the provider, and save.
   Keep the secret in Supabase; it is not a Vercel or browser environment variable.
5. In Supabase **Authentication → URL Configuration**, set the website's HTTPS
   origin as Site URL and allow its exact `/auth/callback` URL. Set the same origin
   in Vercel's server-only `CAREER_KITCHEN_SITE_URL`, and keep the existing
   `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY`.

For the current deployment, the LinkedIn redirect is
`https://dlglvzjmzdxikuolkmio.supabase.co/auth/v1/callback`; the Supabase application
redirect is `https://careerkitchen.vercel.app/auth/callback`. These are two
different steps in the redirect chain. Preview or local websites require their
own explicit allowed application callback URLs.

See [Supabase's LinkedIn setup guide](https://supabase.com/docs/guides/auth/social-login/auth-linkedin).

## Session and onboarding behavior

The browser starts sign-in through a same-origin `POST /api/auth/oauth`. The
server's maintained Supabase SSR client creates the PKCE verifier and keeps it
in HttpOnly, Secure production cookies. Supabase manages the provider OAuth
state. `/auth/callback` exchanges the one-time code and writes the session through
that same cookie adapter. No LinkedIn access token is returned to browser code.

A one-hour HttpOnly cookie carries only the chosen workspace and whether setup
was requested. The callback consumes it and selects one of the application's
fixed workspace or onboarding paths. It does not accept arbitrary `next` URLs
or use provider metadata to grant employer permissions. Company authorization
remains in the backend membership model. Cancelled, expired, and failed flows
return to sign-in with fixed, actionable messages; raw provider errors are never
shown.

LinkedIn OIDC offers basic name, picture, and optional email details, rather than
employment history, skills, or resumes. Members still complete and review their
Career Kitchen profile. LinkedIn can omit both email and email verification;
backend confirmed-email requirements still apply. Signing in with LinkedIn is
not evidence of professional identity or hiring authority. See
[LinkedIn's OIDC documentation](https://learn.microsoft.com/en-us/linkedin/consumer/integrations/self-serve/sign-in-with-linkedin-v2).

## Verification

Run `node --conditions=react-server --test tests/oauth-auth.test.mjs`. It covers
CSRF rejection, provider availability and outages, exact authorization URL
validation, fixed callback destinations, sanitized errors, and the real SSR
client's PKCE cookie persistence without contacting LinkedIn.

Live verification requires configured provider credentials and an account owner
to complete LinkedIn's consent screen. Verify new candidate and employer setup,
returning sign-in, cancellation, and sign-out. An automated or mocked test does
not establish that the external provider is configured or approved.
