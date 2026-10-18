import {
  assertSameOrigin,
  errorResponse,
  GatewayError,
  requestHostname,
} from "@/lib/server/http-utils";
import {
  authMode,
  fictionalToken,
  setFictionalSession,
  supabaseServer,
} from "@/lib/server/session";
import { Backend } from "@/lib/server/backend";
import { cookies } from "next/headers";
import {
  AUTH_INTENT_COOKIE,
  authDestination,
  authIntent,
  authSiteOrigin,
} from "@/lib/server/auth-navigation";

export async function POST(request: Request) {
  try {
    assertSameOrigin(request);
    if (Number(request.headers.get("content-length") || 0) > 10000)
      throw new GatewayError(
        413,
        "REQUEST_TOO_LARGE",
        "Sign-in request is too large.",
      );
    const body = await request.text();
    if (Buffer.byteLength(body) > 10000)
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
        "Enter valid sign-in details.",
      );
    }
    if (!input || typeof input !== "object" || Array.isArray(input))
      throw new GatewayError(
        422,
        "INVALID_CREDENTIALS",
        "Enter valid sign-in details.",
      );
    const mode = authMode(requestHostname(request));
    const role = input.role === "employer" ? "employer" : "candidate";
    const intent = authIntent({ role, mode: input.mode });
    if (mode === "local") {
      const account = String(input.account || "");
      const token = fictionalToken(account);
      await new Backend(token).get("/v1/sessions/me");
      await setFictionalSession(token);
      return Response.json(
        { redirectTo: account === "employer" ? "/employer" : "/candidate" },
        { headers: { "Cache-Control": "no-store" } },
      );
    }
    if (mode !== "supabase")
      throw new GatewayError(
        503,
        "AUTH_NOT_CONFIGURED",
        "Configure Supabase before creating an account.",
      );
    if (
      typeof input.email !== "string" ||
      !/^\S+@\S+\.\S+$/.test(input.email) ||
      typeof input.password !== "string" ||
      input.password.length < 8 ||
      input.password.length > 200
    )
      throw new GatewayError(
        422,
        "INVALID_CREDENTIALS",
        "Enter a valid email and a password of 8–200 characters.",
      );
    const supabase = await supabaseServer();
    const result =
      input.mode === "get-started"
        ? await supabase.auth.signUp({
            email: input.email,
            password: input.password,
            options: {
              emailRedirectTo: new URL(
                "/auth/callback",
                authSiteOrigin(request),
              ).href,
            },
          })
        : await supabase.auth.signInWithPassword({
            email: input.email,
            password: input.password,
          });
    if (result.error)
      throw new GatewayError(
        400,
        "SIGN_IN_FAILED",
        input.mode === "get-started"
          ? "Account creation failed. Check your details or try signing in."
          : "Sign-in failed. Check your credentials and email confirmation.",
      );
    if (!result.data.session)
      (await cookies()).set(AUTH_INTENT_COOKIE, JSON.stringify(intent), {
        httpOnly: true,
        secure: process.env.NODE_ENV === "production",
        sameSite: "lax",
        path: "/",
        maxAge: 3600,
      });
    return Response.json(
      {
        needsEmailConfirmation: !result.data.session,
        redirectTo: authDestination(intent),
      },
      { headers: { "Cache-Control": "no-store" } },
    );
  } catch (error) {
    return errorResponse(error);
  }
}
