import { supabaseServer } from "@/lib/server/session";
import { cookies } from "next/headers";
import {
  AUTH_INTENT_COOKIE,
  authDestination,
  authRedirect,
  authSiteOrigin,
  parseAuthIntent,
} from "@/lib/server/auth-navigation";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const store = await cookies();
  const intent = parseAuthIntent(store.get(AUTH_INTENT_COOKIE)?.value);
  store.delete(AUTH_INTENT_COOKIE);
  const origin = authSiteOrigin(request);
  const failure = new URL("/sign-in", origin);
  failure.searchParams.set("role", intent.role);
  // Never render provider-supplied error descriptions or accept a `next` redirect.
  if (url.searchParams.has("error")) {
    failure.searchParams.set(
      "auth_error",
      url.searchParams.get("error") === "access_denied"
        ? "cancelled"
        : "failed",
    );
    return authRedirect(failure);
  }
  const code = url.searchParams.get("code");
  if (code && code.length <= 4096) {
    try {
      const supabase = await supabaseServer();
      const result = await supabase.auth.exchangeCodeForSession(code);
      if (!result.error && result.data.session) {
        // LinkedIn may omit email. Do not send an unusable session into a workspace.
        if (!result.data.user?.email || !result.data.user.email_confirmed_at) {
          try {
            await supabase.auth.signOut({ scope: "local" });
          } catch {
            // The backend's verified-email check remains authoritative.
          }
          failure.searchParams.set("auth_error", "email_required");
          return authRedirect(failure);
        }
        return authRedirect(new URL(authDestination(intent), origin));
      }
    } catch {
      // An expired or cross-browser PKCE verifier must lead back to sign-in.
    }
  }
  failure.searchParams.set("auth_error", "expired");
  return authRedirect(failure);
}
