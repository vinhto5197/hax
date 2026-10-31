import { expect, test, type Page, type Route } from "@playwright/test";
import {
  composer,
  openNewChat,
  REPLY,
  send,
  sidebarLink,
  startConversation,
} from "./chat";
import { cutStream, installStreamCut } from "./network";

// The fake model streams twenty "Long reply, part N. " deltas 500 ms apart
// for a "long:" prompt (fake-model/server.mjs), about ten seconds: the reply
// is certainly still running when the page reloads, switches or loses the
// connection.
const STILL = "Still answering…";
const INTERRUPTED = "The reply was interrupted.";
const NOT_SENT =
  "Your message wasn't sent. Check your connection and try again.";
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

test("Losing the connection during a reply shows Still answering without an error, then the whole reply, and a reload shows it stored whole", async ({
  page,
}) => {
  test.setTimeout(60_000);
  const first = "Still answering journey: before the connection drops";
  const text = "long: still answering journey, the connection drops mid-reply";
  const main = page.getByRole("main");

  await installStreamCut(page);
  await page.goto("/chat");
  await startConversation(page, first);
  await send(page, text);
  await expect(main.getByText("Long reply, part 1.")).toBeVisible();

  await cutStream(page);
  await expectStillAnswering(page, text);
  await page.waitForTimeout(3_000);
  await expect(stillAnswering(page)).toBeVisible();
  await expect(noErrorLine(page)).toHaveCount(0);

  await expectWholeReply(page, text);

  // The partial at cut time varies, so only the stored whole is asserted.
  await page.reload();
  const stored = main.getByText(/Long reply, part/);
  await expect(stored).toHaveCount(1, { timeout: REPLY_LANDS_MS });
  await expect(stored).toHaveText(LONG_REPLY);
});

// The page polls the conversation for about four seconds before deciding a
// message never arrived, so the NOT_SENT line gets a long timeout.
test("A message that never reaches the server says it wasn't sent and puts the text back in the composer", async ({
  page,
}) => {
  test.setTimeout(60_000);
  const first = "Still answering journey: before a message is lost";
  const text = "Still answering journey: this message never arrives";
  const main = page.getByRole("main");

  await page.goto("/chat");
  await startConversation(page, first);

  let markAborted = () => {};
  const aborted = new Promise<void>((resolve) => (markAborted = resolve));
  // POST only: a CORS preflight to the same URL must pass, not be the one
  // aborted.
  const handler = async (route: Route) => {
    if (route.request().method() !== "POST") {
      await route.continue();
      return;
    }
    await route.abort("internetdisconnected");
    await page.unroute("**/api/chat", handler);
    markAborted();
  };
  await page.route("**/api/chat", handler);

  await send(page, text);
  await aborted;

  await expect(main.getByText(NOT_SENT)).toBeVisible({ timeout: 10_000 });
  await expect(composer(page)).toHaveValue(text);
  await expect(stillAnswering(page)).toHaveCount(0);

  await page.reload();
  await expect(main.getByText(first, { exact: true })).toBeVisible();
  await expect(main.getByText(REPLY, { exact: true })).toHaveCount(1);
  await expect(main.getByText(text, { exact: true })).toHaveCount(0);
});
