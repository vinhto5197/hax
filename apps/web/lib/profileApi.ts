import { API_BASE, apiFetch } from "@/lib/chatApi";
import type { components } from "@/lib/openapi";

export type ProfileOut = components["schemas"]["ProfileOut"];

// The member's note about themselves. Both throw on any non-2xx (a 422
// included): the dialog shows one fixed error line, never the server's detail.
export async function getProfile(): Promise<ProfileOut> {
  const response = await apiFetch(`${API_BASE}/api/me/profile`);
  if (!response.ok) {
    throw new Error(`API ${response.status}: ${response.statusText}`);
  }
  return response.json();
}

export async function saveProfile(about: string): Promise<ProfileOut> {
  const response = await apiFetch(`${API_BASE}/api/me/profile`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ about }),
  });
  if (!response.ok) {
    throw new Error(`API ${response.status}: ${response.statusText}`);
  }
  return response.json();
}
