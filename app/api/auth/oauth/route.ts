import { cookies } from "next/headers";
import {
  assertSameOrigin,
  errorResponse,
  GatewayError,
  requestHostname,
} from "@/lib/server/http-utils";
import { authMode, supabaseServer } from "@/lib/server/session";
import {
  AUTH_INTENT_COOKIE,
  authIntent,
  authSiteOrigin,
  linkedInAvailability,
  validLinkedInAuthorizationUrl,
} from "@/lib/server/auth-navigation";

export async function POST(request: Request) {
  try {
    assertSameOrigin(request);
    if (authMode(requestHostname(request)) !== "supabase")
      throw new GatewayError(
        503,
        "AUTH_NOT_CONFIGURED",
        "Sign-in is not configured.",
      );
    if (Number(request.headers.get("content-length") || 0) > 1000)
      throw new GatewayError(
        413,
        "REQUEST_TOO_LARGE",
        "Sign-in request is too large.",
      );
    const body = await request.text();
    if (Buffer.byteLength(body) > 1000)
      throw new GatewayError(
        413,
        "REQUEST_TOO_LARGE",
        "Sign-in request is too large.",
      );
    let input;
    try {
      input = JSON.parse(body);
    } catch {
      throw new GatewayError(
        422,
        "INVALID_JSON",
        "Reload this page and try signing in again.",
      );
    }
    if (!input || typeof input !== "object" || Array.isArray(input))
      throw new GatewayError(
        422,
        "INVALID_JSON",
        "Reload this page and try signing in again.",
      );
    if ((await linkedInAvailability()) !== "enabled")
      throw new GatewayError(
        503,
        "LINKEDIN_UNAVAILABLE",
        "LinkedIn sign-in is not available yet. Please use email to continue.",
      );
    const intent = authIntent(input);
    const supabase = await supabaseServer();
    // Supabase SSR generates a PKCE verifier in the existing HttpOnly cookie store.
    const { data, error } = await supabase.auth.signInWithOAuth({
      provider: "linkedin_oidc",
      options: {
        scopes: "openid profile email",
        redirectTo: new URL("/auth/callback", authSiteOrigin(request)).href,
        skipBrowserRedirect: true,
      },
    });
    if (error || !data.url || !validLinkedInAuthorizationUrl(data.url))
      throw new GatewayError(
        503,
        "LINKEDIN_UNAVAILABLE",
        "LinkedIn sign-in could not start. Please use email or try again later.",
      );
    (await cookies()).set(AUTH_INTENT_COOKIE, JSON.stringify(intent), {
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      sameSite: "lax",
      path: "/",
      maxAge: 3600,
    });
    return Response.json(
      { redirectTo: data.url },
      { headers: { "Cache-Control": "no-store" } },
    );
  } catch (error) {
    return errorResponse(error);
  }
}
