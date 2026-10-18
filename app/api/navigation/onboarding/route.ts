import { createNavigationBridge } from "@/lib/server/navigation-bridge";
import { accessToken } from "@/lib/server/session";

export const runtime = "nodejs";

export async function POST(request: Request) {
  return createNavigationBridge(
    process.env,
    fetch,
    accessToken,
    "v1/navigation/onboarding",
  ).POST(request);
}
