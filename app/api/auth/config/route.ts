import { authMode } from "@/lib/server/session";
import { requestHostname } from "@/lib/server/http-utils";
import { linkedInAvailability } from "@/lib/server/auth-navigation";
export async function GET(request: Request) {
  const mode = authMode(requestHostname(request));
  return Response.json(
    {
      mode,
      ...(mode === "supabase"
        ? { linkedin: await linkedInAvailability() }
        : {}),
      ...(mode === "local"
        ? {
            accounts: [
              "employer",
              ...Array.from(
                { length: 30 },
                (_, i) => `candidate-${String(i + 1).padStart(2, "0")}`,
              ),
            ],
          }
        : {}),
    },
    { headers: { "Cache-Control": "no-store" } },
  );
}
