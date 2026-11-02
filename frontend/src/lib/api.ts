import { z } from "zod";
import { API_BASE_URL } from "@/lib/runtime-config";
const healthSchema = z.object({ status: z.string() }).passthrough();

export async function apiFetch<T>(path: string, schema: z.ZodType<T>, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  if (method !== "GET" && method !== "HEAD" && typeof document !== "undefined") {
    const csrf = document.cookie.split(";").map(value => value.trim()).find(value => value.startsWith("mythos_dashboard_csrf="))?.split("=").slice(1).join("=");
    if (csrf) headers.set("X-Mythos-CSRF", decodeURIComponent(csrf));
  }
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    method,
    headers,
    credentials: "include",
    cache: init.cache ?? "no-store",
  });
  const data: unknown = await response.json();
  if (!response.ok) throw new Error(`MythosLive API request failed (${response.status})`);
  return schema.parse(data);
}

export function getApiReadiness() {
  return apiFetch("/readyz", healthSchema);
}
