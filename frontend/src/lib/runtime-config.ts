const configuredApiUrl = process.env.NEXT_PUBLIC_API_URL?.trim();

if (process.env.NODE_ENV === "production" && !configuredApiUrl) {
  throw new Error("NEXT_PUBLIC_API_URL must be set for production builds.");
}

export const API_BASE_URL = (configuredApiUrl ?? "http://localhost:8000").replace(/\/$/, "");
export const API_WEBSOCKET_URL = API_BASE_URL.replace(/^http/, "ws");
