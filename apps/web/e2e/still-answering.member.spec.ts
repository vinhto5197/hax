import { expect, test, type Page } from "@playwright/test";
import {
  composer,
  openNewChat,
  REPLY,
  send,
  sidebarLink,
  startConversation,
} from "./chat";

// The fake model streams twenty "Long reply, part N. " deltas 500 ms apart
// for a "long:" prompt (fake-model/server.mjs), about ten seconds: the reply
// is certainly still running when the page reloads, switches or goes offline.
const STILL = "Still answering…";
const INTERRUPTED = "The reply was interrupted.";
const LONG_REPLY = Array.from(
  { length: 20 },
  (_, i) => `Long reply, part ${i + 1}. `,
)
  .join("")
  .trim();
// The reply ends about ten seconds after its first part; the page checks
// back every two seconds.
const REPLY_LANDS_MS = 25_000;
const DESKTOP = { width: 1280, height: 800 };
const PHONE = { width: 390, height: 844 };

// Scoped to the chat: Next.js renders an empty role="alert" route announcer
// outside it on every page.
function noErrorLine(page: Page) {
  return page.getByRole("main").getByRole("alert");
}

function stillAnswering(page: Page) {
  return page.getByRole("status").filter({ hasText: STILL });
}

async function expectStillAnswering(page: Page, text: string) {
  const main = page.getByRole("main");
  await expect(main.getByText(text, { exact: true })).toBeVisible();
  await expect(stillAnswering(page)).toBeVisible();
  await expect(stillAnswering(page)).toHaveText(STILL);
  await expect(composer(page)).toBeDisabled();
  await expect(main.getByText(/Long reply, part/)).toHaveCount(0);
  await expect(noErrorLine(page)).toHaveCount(0);
}

async function expectWholeReply(page: Page, text: string) {
  const main = page.getByRole("main");
  await expect(main.getByText(LONG_REPLY, { exact: true })).toBeVisible({
    timeout: REPLY_LANDS_MS,
  });
  await expect(stillAnswering(page)).toHaveCount(0);
  await expect(composer(page)).toBeEnabled();
  await expect(main.getByText(text, { exact: true })).toHaveCount(1);
  await expect(page.getByText(INTERRUPTED)).toHaveCount(0);
  await expect(noErrorLine(page)).toHaveCount(0);
}

test("Reloading during a reply shows the message and Still answering with the composer disabled, then the whole reply", async ({
  page,
}, testInfo) => {
  test.setTimeout(60_000);
  const text = "long: still answering journey, reloaded mid-reply";
  const main = page.getByRole("main");
  await page.setViewportSize(DESKTOP);

  await page.goto("/chat");
  await send(page, text);
  await expect(main.getByText("Long reply, part 1.")).toBeVisible();
  await expect(page).toHaveURL(/\/chat\/[^/]+$/);

  await page.reload();
  await expectStillAnswering(page, text);

  const desktopShot = testInfo.outputPath("still-answering-desktop.png");
  await page.screenshot({ path: desktopShot, fullPage: true });
  await testInfo.attach("still answering, desktop", {
    path: desktopShot,
    contentType: "image/png",
  });
  await page.setViewportSize(PHONE);
  await expect(stillAnswering(page)).toBeVisible();
  const phoneShot = testInfo.outputPath("still-answering-phone.png");
  await page.screenshot({ path: phoneShot, fullPage: true });
  await testInfo.attach("still answering, phone", {
    path: phoneShot,
    contentType: "image/png",
  });
  await page.setViewportSize(DESKTOP);

  await expectWholeReply(page, text);
});

test("Switching to another conversation during a reply and back shows Still answering, then the whole reply", async ({
  page,
}) => {
  test.setTimeout(60_000);
  const first = "Still answering journey: the first message";
  const text = "long: still answering journey, switched away mid-reply";
  const main = page.getByRole("main");

  await page.goto("/chat");
  const path = await startConversation(page, first);
  await send(page, text);
  await expect(main.getByText("Long reply, part 1.")).toBeVisible();

  await openNewChat(page);
  await expect(main.getByText(text)).toHaveCount(0);
  await sidebarLink(page, path).click();
  await expect(page).toHaveURL(new RegExp(`${path}$`));

  await expectStillAnswering(page, text);
  await expect(main.getByText(first, { exact: true })).toBeVisible();
  await expect(main.getByText(REPLY, { exact: true })).toHaveCount(1);

  await expectWholeReply(page, text);
  await expect(main.getByText(REPLY, { exact: true })).toHaveCount(1);
});

test("Losing the network during a reply shows Still answering without an error, then the whole reply once back online", async ({
  page,
  context,
}) => {
  test.skip(
    true,
    "Chromium's offline emulation does not cut a response already streaming: probed 2026-10-27, an open fetch body kept delivering every chunk to EOF after context.setOffline(true), and only new requests failed. The lost connection cannot be staged this way; the unit suites cover it.",
  );
  test.setTimeout(60_000);
  const first = "Still answering journey: before going offline";
  const text = "long: still answering journey, the network drops mid-reply";
  const main = page.getByRole("main");

  await page.goto("/chat");
  await startConversation(page, first);
  await send(page, text);
  await expect(main.getByText("Long reply, part 1.")).toBeVisible();

  await context.setOffline(true);
  await expectStillAnswering(page, text);
  await page.waitForTimeout(3_000);
  await expect(stillAnswering(page)).toBeVisible();
  await expect(noErrorLine(page)).toHaveCount(0);

  await context.setOffline(false);
  await expectWholeReply(page, text);
});
