import "server-only";
import { GatewayError, isLoopbackHost } from "./http-utils";

export const AUTH_INTENT_COOKIE = "ck-auth-intent";
export type AuthIntent = {
  role: "candidate" | "employer";
  mode: "sign-in" | "get-started";
};

// This is a navigation preference, never a company membership or permission.
export function authIntent(input: {
  role?: unknown;
  mode?: unknown;
}): AuthIntent {
  return {
    role: input.role === "employer" ? "employer" : "candidate",
    mode: input.mode === "get-started" ? "get-started" : "sign-in",
  };
}

export function parseAuthIntent(value: string | undefined): AuthIntent {
  try {
    const parsed = JSON.parse(value || "{}");
    return authIntent(parsed && typeof parsed === "object" ? parsed : {});
  } catch {
    return authIntent({});
  }
}

export function authDestination(intent: AuthIntent) {
  return intent.mode === "get-started"
    ? `/onboarding/${intent.role}`
    : `/${intent.role}`;
}

export function authSiteOrigin(request: Request) {
  const configured = process.env.CAREER_KITCHEN_SITE_URL;
  const url = new URL(configured || request.url);
  if (
    url.username ||
    url.password ||
    (configured && (url.pathname !== "/" || url.search || url.hash)) ||
    (url.protocol !== "https:" &&
      !(url.protocol === "http:" && isLoopbackHost(url.hostname)))
  )
    throw new GatewayError(
      503,
      "AUTH_NOT_CONFIGURED",
      "Sign-in is temporarily unavailable. Please try again later.",
    );
  return url.origin;
}

export function supabaseConnection() {
  return {
    url: process.env.SUPABASE_URL || process.env.NEXT_PUBLIC_SUPABASE_URL,
    key:
      process.env.SUPABASE_PUBLISHABLE_KEY ||
      process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY,
  };
}

export async function linkedInAvailability(): Promise<
  "enabled" | "disabled" | "unavailable"
> {
  const { url, key } = supabaseConnection();
  if (!url || !key) return "unavailable";
  try {
    const response = await fetch(new URL("/auth/v1/settings", url), {
      headers: { apikey: key },
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) return "unavailable";
    const settings = await response.json();
    return settings?.external?.linkedin_oidc === true ? "enabled" : "disabled";
  } catch {
    return "unavailable";
  }
}

export function validLinkedInAuthorizationUrl(value: string) {
  try {
    const { url } = supabaseConnection();
    const target = new URL(value);
    return (
      Boolean(url) &&
      !target.username &&
      !target.password &&
      target.origin === new URL(url!).origin &&
      target.pathname === "/auth/v1/authorize" &&
      target.searchParams.get("provider") === "linkedin_oidc"
    );
  } catch {
    return false;
  }
}

export function authRedirect(target: URL) {
  return new Response(null, {
    status: 303,
    headers: { Location: target.href, "Cache-Control": "no-store" },
  });
}
