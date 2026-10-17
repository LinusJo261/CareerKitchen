import createClient from "openapi-fetch";
import type { paths, components } from "./schema.js";

export type { paths, components } from "./schema.js";

export interface ClientOptions {
  baseUrl: string;
  /** Obtain this request's Supabase access token from the server-side session. */
  accessToken: () => string | Promise<string>;
  fetch?: typeof globalThis.fetch;
  timeoutMs?: number;
}

type PostOperation<P extends keyof paths> = paths[P] extends { post: infer Operation } ? Operation : never;
type MultipartSchema<Operation> = Operation extends { requestBody: { content: { "multipart/form-data": infer Body } } } ? Body : never;
type MultipartPath = { [P in keyof paths]: [MultipartSchema<PostOperation<P>>] extends [never] ? never : P }[keyof paths];
type MultipartFields<Operation> = { [K in keyof MultipartSchema<Operation>]: K extends "file" ? Blob : MultipartSchema<Operation>[K] };
type OperationParameters<Operation> = Operation extends { parameters: infer Parameters } ? Parameters : never;
type SuccessBody<Operation> = Operation extends { responses: infer Responses } ? {
  [Status in keyof Responses]: Status extends 200 | 201 | 202 ? Responses[Status] extends { content: { "application/json": infer Body } } ? Body : never : never
}[keyof Responses] : never;

export class CareerKitchenApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly requestId?: string,
  ) {
    super(message);
    this.name = "CareerKitchenApiError";
  }
}

/** Create once per incoming BFF request. Never share a user's token in a global singleton. */
export function createCareerKitchenClient(options: ClientOptions) {
  if (typeof window !== "undefined") {
    throw new Error("Career Kitchen's API client must run in a server-side BFF");
  }
  const base = new URL(options.baseUrl);
  if (base.username || base.password || base.search || base.hash) {
    throw new Error("API base URL cannot contain credentials, a query, or a fragment");
  }
  if (base.protocol !== "https:" && !(base.protocol === "http:" && ["localhost", "127.0.0.1", "[::1]"].includes(base.hostname))) {
    throw new Error("API connections require HTTPS or a loopback development URL");
  }
  const fetchImpl = options.fetch ?? globalThis.fetch;
  const timeoutMs = options.timeoutMs ?? 15_000;
  if (!Number.isInteger(timeoutMs) || timeoutMs < 100 || timeoutMs > 60_000) {
    throw new Error("API timeout must be 100–60000 milliseconds");
  }
  const basePath = base.pathname.replace(/\/$/, "");
  const authenticatedFetch: typeof globalThis.fetch = async (input, init) => {
    const request = new Request(input, init);
    const target = new URL(request.url);
    if (target.origin !== base.origin || (basePath && target.pathname !== basePath && !target.pathname.startsWith(`${basePath}/`))) {
      throw new Error("Refusing to send a session to another API origin or base path");
    }
    const headers = new Headers(request.headers);
    if (!["GET", "HEAD", "OPTIONS"].includes(request.method)) {
      if (!/^[A-Za-z0-9_.:-]{8,128}$/.test(headers.get("Idempotency-Key") ?? "")) {
        throw new Error("Supply a stable Idempotency-Key for this mutation; reuse it only for an exact retry");
      }
    }
    const token = await options.accessToken();
    if (!token || /[\r\n]/.test(token)) throw new Error("An authenticated Supabase session is required");
    headers.set("Authorization", `Bearer ${token}`);
    if (!headers.has("X-Request-ID")) headers.set("X-Request-ID", crypto.randomUUID());
    const signal = AbortSignal.any([request.signal, AbortSignal.timeout(timeoutMs)]);
    // Exactly one request. Stale-state, capacity, rate-limit and network failures return to the caller.
    return fetchImpl(new Request(request, { headers, signal, cache: "no-store", redirect: "error" }));
  };
  const baseUrl = options.baseUrl.replace(/\/$/, "");
  const client = createClient<paths>({ baseUrl, fetch: authenticatedFetch });
  /** Multipart files are Blobs; generated schemas otherwise represent binary fields as strings. */
  async function uploadMultipart<P extends MultipartPath>(path: P, upload: {
    params: OperationParameters<PostOperation<P>>;
    body: MultipartFields<PostOperation<P>>;
    signal?: AbortSignal;
  }) {
    const parameters = upload.params as {
      path?: Record<string, string | number>;
      query?: Record<string, unknown>;
      header?: Record<string, string>;
    };
    const pathname = path.replace(/\{([^}]+)\}/g, (_placeholder, name: string) => {
      const value = parameters.path?.[name];
      if (value === undefined) throw new Error(`Missing upload path parameter: ${name}`);
      return encodeURIComponent(String(value));
    });
    const url = new URL(`${baseUrl}${pathname}`);
    for (const [key, value] of Object.entries(parameters.query ?? {})) {
      if (value !== undefined && value !== null) url.searchParams.set(key, String(value));
    }
    const form = new FormData();
    for (const [key, value] of Object.entries(upload.body as Record<string, unknown>)) {
      if (value !== undefined && value !== null) {
        if (value instanceof Blob) form.append(key, value, "document");
        else form.append(key, String(value));
      }
    }
    const init: RequestInit = { method: "POST", headers: parameters.header ?? {}, body: form };
    if (upload.signal) init.signal = upload.signal;
    const response = await authenticatedFetch(new Request(url, init));
    const payload: unknown = await response.json();
    if (!response.ok) throw apiError(response, payload);
    return payload as SuccessBody<PostOperation<P>>;
  }
  return Object.assign(client, { uploadMultipart });
}

/** Make a key when the user starts an operation and retain it across transport retries. */
export function newOperationKey(): string {
  return crypto.randomUUID();
}

/** Normalize an error without logging tokens or serializing potentially private response content. */
export function apiError(response: Response, payload: unknown): CareerKitchenApiError {
  const body = payload && typeof payload === "object" && "error" in payload ? payload.error : undefined;
  const safe = body && typeof body === "object" ? body as Record<string, unknown> : {};
  return new CareerKitchenApiError(
    response.status,
    typeof safe.code === "string" ? safe.code : "API_ERROR",
    typeof safe.message === "string" ? safe.message : "The API request failed",
    typeof safe.request_id === "string" ? safe.request_id : undefined,
  );
}

