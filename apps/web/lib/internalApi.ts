// Next's server-side calls to the API's /internal/auth/* routes (auth.ts).
// Without a limit, an API that never answers leaves the login button on
// "Logging in…" for minutes; with it, the call fails in seconds with
// InternalApiTimeout, which auth.ts turns into the sign-in code "timeout".
export const INTERNAL_API_TIMEOUT_MS = 10_000;

export class InternalApiTimeout extends Error {}

export async function internalFetch(
  url: string,
  init: RequestInit,
): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), INTERNAL_API_TIMEOUT_MS);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } catch (error) {
    if (controller.signal.aborted) throw new InternalApiTimeout();
    throw error;
  } finally {
    clearTimeout(timer);
  }
}
