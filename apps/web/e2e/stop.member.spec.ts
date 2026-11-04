import { expect, test, type Page } from "@playwright/test";
import { composer, REPLY, send } from "./chat";

// The fake model streams twenty "Long reply, part N. " deltas 500 ms apart
// for a "long:" prompt (fake-model/server.mjs), about ten seconds: Stop is
// certainly pressed while the reply runs, and waiting the rest of those ten
// seconds shows whether it kept growing.
const STILL = "Still answering…";
const INTERRUPTED = "The reply was interrupted.";
const STOPPED = "You stopped this reply.";
const LONG_REPLY = Array.from(
  { length: 20 },
  (_, i) => `Long reply, part ${i + 1}. `,
)
  .join("")
  .trim();
const REPLY_RUNS_MS = 11_000;
const REPLY_LANDS_MS = 25_000;

function stopButton(page: Page) {
  return page.getByRole("button", { name: "Stop" });
}

function sendButton(page: Page) {
  return page.getByRole("button", { name: "Send", exact: true });
}

// Scoped to the chat: Next.js renders an empty role="alert" route announcer
// outside it on every page.
function errorLine(page: Page) {
  return page.getByRole("main").getByRole("alert");
}

// The thread's activity line; the stopped line is also a status, so it is
// left out.
function activityLine(page: Page) {
  return page
    .getByRole("main")
    .getByRole("status")
    .filter({ hasNotText: STOPPED });
}

function longReply(page: Page) {
  return page.getByRole("main").getByText(/Long reply, part 1\./);
}

test("Stop during a reply keeps what was written, frees the composer, and a reload shows the same partial reply", async ({
  page,
}) => {
  test.setTimeout(60_000);
  const text = "long: stop journey, stopped mid-reply";
  const main = page.getByRole("main");

  await page.goto("/chat");
  await send(page, text);
  await expect(main.getByText("Long reply, part 2.")).toBeVisible();
  await expect(stopButton(page)).toBeEnabled();
  await stopButton(page).click();

  await expect(composer(page)).toBeEnabled();
  await expect(stopButton(page)).toHaveCount(0);
  await expect(errorLine(page)).toHaveCount(0);
  const partial = ((await longReply(page).textContent()) ?? "").trim();
  expect(partial).toContain("Long reply, part 2.");
  expect(partial).not.toContain("Long reply, part 20.");

  // The rest of the reply's running time: a reply that was not stopped
  // would reach its last part within it.
  await page.waitForTimeout(REPLY_RUNS_MS);
  await expect(main.getByText(/Long reply, part 20\./)).toHaveCount(0);
  await expect(longReply(page)).toHaveText(partial);
  await expect(errorLine(page)).toHaveCount(0);
  await expect(page.getByText(INTERRUPTED)).toHaveCount(0);

  await expect(page).toHaveURL(/\/chat\/[^/]+$/);
  await page.reload();
  await expect(main.getByText(text, { exact: true })).toBeVisible();
  await expect(longReply(page)).toHaveText(partial);
  await expect(main.getByText(/Long reply, part 20\./)).toHaveCount(0);
  await expect(page.getByText(INTERRUPTED)).toHaveCount(0);
  await expect(composer(page)).toBeEnabled();

  await send(page, "Stop journey: the next message after a stop");
  await expect(main.getByText(REPLY, { exact: true })).toBeVisible();
  await expect(errorLine(page)).toHaveCount(0);
});

test("A stop request still pending after the reply ended shows no activity line under the kept reply", async ({
  page,
}) => {
  test.setTimeout(60_000);
  const main = page.getByRole("main");
  let release!: () => void;
  const released = new Promise<void>((r) => {
    release = r;
  });
  let reached!: () => void;
  const serverStopped = new Promise<void>((r) => {
    reached = r;
  });
  // The server receives the stop at once; only its 204 is held back.
  await page.route("**/api/conversations/*/stop", async (route) => {
    const response = await route.fetch();
    reached();
    await released;
    await route.fulfill({ response });
  });

  await page.goto("/chat");
  await send(page, "long: stop journey, slow stop request");
  await expect(main.getByText("Long reply, part 2.")).toBeVisible();
  await stopButton(page).click();
  await serverStopped;

  // The reply's [DONE] lands while the stop's 204 is still held.
  await page.waitForTimeout(1_500);
  await expect(composer(page)).toBeDisabled();
  await expect(longReply(page)).toBeVisible();
  await expect(activityLine(page)).toHaveCount(0);

  release();
  await expect(composer(page)).toBeEnabled();
  await expect(activityLine(page)).toHaveCount(0);
  await expect(errorLine(page)).toHaveCount(0);
});

test("Still answering offers no Stop: Send shows, disabled", async ({
  page,
}) => {
  test.setTimeout(60_000);
  const text = "long: stop journey, reloaded mid-reply";
  const main = page.getByRole("main");

  await page.goto("/chat");
  await send(page, text);
  await expect(main.getByText("Long reply, part 1.")).toBeVisible();
  await expect(page).toHaveURL(/\/chat\/[^/]+$/);

  await page.reload();
  await expect(
    page.getByRole("status").filter({ hasText: STILL }),
  ).toBeVisible();
  await expect(stopButton(page)).toHaveCount(0);
  await expect(sendButton(page)).toBeVisible();
  await expect(sendButton(page)).toBeDisabled();
  await expect(composer(page)).toBeDisabled();

  await expect(main.getByText(LONG_REPLY, { exact: true })).toBeVisible({
    timeout: REPLY_LANDS_MS,
  });
  await expect(composer(page)).toBeEnabled();
  await expect(stopButton(page)).toHaveCount(0);
  await composer(page).fill("Stop journey: after Still answering");
  await expect(sendButton(page)).toBeEnabled();
});
