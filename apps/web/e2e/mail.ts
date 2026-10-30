import type { APIRequestContext } from "@playwright/test";

// Dev Mailpit (a service container in CI), where the journey stack's
// SMTP_PORT sends. The inbox is shared with dev mail and every journey that
// sends, so a message is found by its recipient, never as "the latest".
const MAILPIT_URL = "http://localhost:8025";
// The API builds links from APP_BASE_URL, which playwright.config.ts sets.
const WEB_URL = "http://localhost:3001";
const POLL_MS = 500;
const TIMEOUT_MS = 20_000;

type SearchResult = { messages?: { ID: string }[] };

// Returns the newest link to `path` mailed to `to`; Mailpit lists newest first.
export async function mailLink(
  request: APIRequestContext,
  to: string,
  path: "/verify-email" | "/reset-password",
): Promise<string> {
  const prefix = `${WEB_URL}${path}?token=`;
  const deadline = Date.now() + TIMEOUT_MS;
  let lastStatus = 0;
  while (true) {
    const search = await request.get(`${MAILPIT_URL}/api/v1/search`, {
      params: { query: `to:"${to}"` },
    });
    lastStatus = search.status();
    if (search.ok()) {
      const { messages = [] } = (await search.json()) as SearchResult;
      for (const { ID } of messages) {
        const message = await request.get(
          `${MAILPIT_URL}/api/v1/message/${ID}`,
        );
        lastStatus = message.status();
        if (!message.ok()) continue;
        const { Text = "" } = (await message.json()) as { Text?: string };
        const start = Text.indexOf(prefix);
        if (start !== -1) return Text.slice(start).split(/\s/, 1)[0];
      }
    }
    if (Date.now() >= deadline) {
      throw new Error(
        `no ${path} email to ${to} within 20 s (last Mailpit status ${lastStatus})`,
      );
    }
    await new Promise((resolve) => setTimeout(resolve, POLL_MS));
  }
}
