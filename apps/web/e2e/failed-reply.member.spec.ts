import { expect, test } from "@playwright/test";
import { REPLY, send } from "./chat";

// The fake model streams "Failing reply, part N. " for a "fail:" prompt, then
// cuts the connection without finishing the message: the API's model-failure
// path, which ends the stream with the reply_failed frame.
const FAIL_TEXT = "fail: failed reply journey, the model breaks off mid-reply";
const RESEND_TEXT = "Failed reply journey: sent after the failure";
const INTERRUPTED = "The reply was interrupted.";
const BUSY = "A reply is already in progress in this conversation.";
const DESKTOP = { width: 1280, height: 800 };
const PHONE = { width: 390, height: 844 };

test("A reply the model breaks off is dropped and reported as interrupted, the user's message stays after a reload, and the conversation takes the next message", async ({
  page,
}, testInfo) => {
  await page.setViewportSize(DESKTOP);
  const main = page.getByRole("main");
  const interrupted = page.getByRole("alert").filter({ hasText: INTERRUPTED });

  await page.goto("/chat");
  await send(page, FAIL_TEXT);
  await expect(main.getByText(FAIL_TEXT, { exact: true })).toBeVisible();
  await expect(main.getByText("Failing reply, part 1.")).toBeVisible();

  await expect(interrupted).toBeVisible();
  await expect(interrupted).toHaveText(INTERRUPTED);
  await expect(main.getByText(/Failing reply/)).toHaveCount(0);
  await expect(main.getByText(FAIL_TEXT, { exact: true })).toBeVisible();
  await expect(page).toHaveURL(/\/chat\/[^/]+$/);

  const desktopShot = testInfo.outputPath("failed-reply-desktop.png");
  await page.screenshot({ path: desktopShot, fullPage: true });
  await testInfo.attach("failed reply, desktop", {
    path: desktopShot,
    contentType: "image/png",
  });
  await page.setViewportSize(PHONE);
  await expect(interrupted).toBeVisible();
  await expect(main.getByText(/Failing reply/)).toHaveCount(0);
  const phoneShot = testInfo.outputPath("failed-reply-phone.png");
  await page.screenshot({ path: phoneShot, fullPage: true });
  await testInfo.attach("failed reply, phone", {
    path: phoneShot,
    contentType: "image/png",
  });
  await page.setViewportSize(DESKTOP);

  await page.reload();
  await expect(main.getByText(FAIL_TEXT, { exact: true })).toBeVisible();
  await expect(main.getByText(/Failing reply/)).toHaveCount(0);
  await expect(main.getByText(REPLY, { exact: true })).toHaveCount(0);
  await expect(interrupted).toHaveCount(0);

  await send(page, RESEND_TEXT);
  await expect(main.getByText(RESEND_TEXT, { exact: true })).toBeVisible();
  await expect(main.getByText(REPLY, { exact: true })).toBeVisible();
  await expect(page.getByText(BUSY)).toHaveCount(0);
  await expect(interrupted).toHaveCount(0);
});
