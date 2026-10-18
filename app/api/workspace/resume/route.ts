import { backendFor } from "@/lib/server/backend";
import {
  assertSameOrigin,
  errorResponse,
  operationKey,
} from "@/lib/server/http-utils";
import { resumeForm } from "@/lib/server/resume-upload";

export async function POST(request: Request) {
  try {
    assertSameOrigin(request);
    const key = operationKey(request);
    const api = await backendFor(request);
    const result = await api.request("/v1/candidates/me/resume", {
      method: "POST",
      key,
      body: await resumeForm(request),
    });
    return Response.json(result, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    return errorResponse(error);
  }
}
