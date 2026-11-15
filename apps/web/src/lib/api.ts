export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "";
// getRandomValues also works on HTTP LAN origins where randomUUID is unavailable.
export function commandKey(): string {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
  const hex = Array.from(bytes,b=>b.toString(16).padStart(2,"0")).join("");
  return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
}
const pendingKeys = new Map<string, string>();

export class ApiError extends Error {
  constructor(public status: number, message: string, public requestId?: string) {
    super(message);
  }
}

function csrfCookie(): string | undefined {
  if (typeof document === "undefined") return undefined;
  return document.cookie
    .split("; ")
    .find((item) => item.startsWith("hutano_csrf="))
    ?.split("=")[1];
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const method = (options.method || "GET").toUpperCase();
  const headers = new Headers(options.headers);
  const commandId = `${method}:${path}:${typeof options.body === "string" ? options.body : "upload"}`;
  if (options.body && !(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    if (typeof navigator !== "undefined" && !navigator.onLine) throw new ApiError(0, "Offline. Reconnect and refresh before submitting this action.");
    const csrf = csrfCookie();
    if (csrf) headers.set("X-CSRF-Token", decodeURIComponent(csrf));
    if (!headers.has("Idempotency-Key")) {
      const key = pendingKeys.get(commandId) || commandKey();
      pendingKeys.set(commandId, key);
      headers.set("Idempotency-Key", key);
    }
  }
  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers,
    credentials: "include",
    cache: "no-store",
  });
  if (!response.ok) {
    if (response.status < 500) pendingKeys.delete(commandId);
    const data = await response.json().catch(() => ({ error: response.statusText }));
    throw new ApiError(response.status, data.error || "Request failed", data.request_id);
  }
  pendingKeys.delete(commandId);
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function formatTime(value?: string | null): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("en-ZW", {
    timeZone: "Africa/Harare",
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export async function waitForJob(jobId: string): Promise<{ result_ref: string }> {
  for (let attempt = 0; attempt < 300; attempt++) {
    const job = await api<{ status: string; result_ref: string; error?: string }>(`/api/v1/research/jobs/${jobId}`);
    if (job.status === "COMPLETED") return job;
    if (job.status === "FAILED") throw new Error(job.error || "Research job failed");
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error("The job is still queued. Open recent jobs to check its durable status.");
}

