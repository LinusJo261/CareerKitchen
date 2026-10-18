"use client";
import { useRef } from "react";
import { usePathname } from "next/navigation";
import useSWR, { useSWRConfig } from "swr";
import { toast } from "sonner";
import { emptyWorkspace, type WorkspaceState } from "./workspace-types";

export type {
  WorkspaceState,
  WorkspaceBackend,
  ApiSchema,
} from "./workspace-types";
export class WorkspaceError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
  }
}
async function readResponse<T>(response: Response): Promise<T> {
  const payload = await response.json().catch(() => null);
  if (!response.ok)
    throw new WorkspaceError(
      response.status,
      payload?.error?.code || "REQUEST_FAILED",
      payload?.error?.message || "The request could not be completed.",
    );
  return payload as T;
}
const pendingKeys = new Map<string, string>();
const manualInvitations = new Map<
  string,
  NonNullable<WorkspaceState["backend"]["lastInvitation"]>
>();
export async function sendWorkspaceCommand<T = unknown>(
  action: string,
  payload: Record<string, unknown> = {},
): Promise<T> {
  const fingerprint = JSON.stringify([action, payload]);
  const key = pendingKeys.get(fingerprint) || crypto.randomUUID();
  pendingKeys.set(fingerprint, key);
  let response: Response;
  try {
    response = await fetch("/api/workspace/commands", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Idempotency-Key": key },
      body: JSON.stringify({ action, payload }),
      cache: "no-store",
    });
  } catch {
    throw new WorkspaceError(
      0,
      "OFFLINE",
      "Connection lost. The change has not been confirmed. Retry the same action to check its result.",
    );
  }
  if (response.ok || (response.status >= 400 && response.status < 500))
    pendingKeys.delete(fingerprint);
  return (await readResponse<{ data: T }>(response)).data;
}

export function useWorkspace() {
  const pathname = usePathname();
  const role = pathname.startsWith("/employer") ? "employer" : "candidate";
  const { mutate: mutateAll } = useSWRConfig();
  const { data, error, mutate, isLoading } = useSWR<WorkspaceState>(
    `/api/workspace?role=${role}`,
    async (url) => {
      const result = await readResponse<WorkspaceState>(
        await fetch(url, { cache: "no-store" }),
      );
      const invitation =
        result.session && manualInvitations.get(result.session.id);
      if (invitation) result.backend.lastInvitation = invitation;
      return result;
    },
    {
      revalidateOnFocus: true,
      refreshInterval: 30000,
      errorRetryCount: 0,
      keepPreviousData: false,
    },
  );
  const busy = useRef(false);
  async function execute(
    action: string,
    payload: Record<string, unknown> = {},
    message?: string,
  ) {
    if (busy.current) return false;
    busy.current = true;
    try {
      let reviewedPayload = payload;
      if (
        action === "candidate.save" &&
        payload.patch &&
        data?.backend.candidate
      ) {
        reviewedPayload = { ...payload, profile: data.backend.candidate };
      }
      if (action === "candidate.preferences" && data?.backend.candidate) {
        const candidate = data.backend.candidate;
        reviewedPayload = {
          compensation_floor: candidate.compensation_floor,
          currency: candidate.currency,
          compensation_period: candidate.compensation_period,
          employment_types: candidate.employment_types,
          work_modes: candidate.work_modes,
          locations: candidate.locations,
          cap: candidate.cap,
          ...payload,
        };
      }
      const result = await sendWorkspaceCommand(action, reviewedPayload);
      if (action === "team.invite" && result && data?.session) {
        manualInvitations.set(data.session.id, {
          ...(result as NonNullable<
            WorkspaceState["backend"]["lastInvitation"]
          >),
          org_id: String(payload.orgId),
        });
      }
      if (action === "session.logout" || action === "privacy.delete") {
        await mutateAll(
          (key) => typeof key === "string" && key.startsWith("/api/workspace"),
          undefined,
          { revalidate: false },
        );
      } else {
        await mutate().catch(() => undefined);
      }
      if (message) toast.success(message);
      return true;
    } catch (error) {
      toast.error(
        error instanceof Error
          ? error.message
          : "The change could not be saved.",
      );
      await mutate().catch(() => undefined);
      return false;
    } finally {
      busy.current = false;
    }
  }
  return {
    data: data || emptyWorkspace(role),
    error: error as WorkspaceError | undefined,
    isLoading,
    execute,
    refresh: () => mutate(),
  };
}
