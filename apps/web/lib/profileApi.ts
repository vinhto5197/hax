import { API_BASE, apiFetch, okJson } from "@/lib/chatApi";
import type { components } from "@/lib/openapi";

export type ProfileOut = components["schemas"]["ProfileOut"];

// The member's note about themselves. Both throw on any non-2xx (a 422
// included): the dialog shows one fixed error line, never the server's detail.
export async function getProfile(): Promise<ProfileOut> {
  return okJson(await apiFetch(`${API_BASE}/api/me/profile`));
}

export async function saveProfile(about: string): Promise<ProfileOut> {
  return okJson(
    await apiFetch(`${API_BASE}/api/me/profile`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ about }),
    }),
  );
}
