import { expect, test, type JSHandle, type Page } from "@playwright/test";
import { composer, REPLY, startConversation } from "./chat";

// A user bubble keeps its line breaks, so one tall turn makes the thread
// scroll at the default desktop viewport.
const TALL_LINES = Array.from({ length: 40 }, (_, i) => `Tall line ${i + 1}`);
const TALL_TEXT = `Thread journey: a tall turn\n${TALL_LINES.join("\n")}`;
const SLOW_TEXT = "slow: thread journey, the reply the view follows";
// Mirrors STICK_THRESHOLD_PX in components/chat/MessageList.tsx.
const STICK_THRESHOLD_PX = 64;

// The thread's scroll container has no role or label: it is the first
// scrollable element in main, ahead of the composer.
async function threadScroller(page: Page) {
  return page.getByRole("main").evaluateHandle((main) => {
    const divs = Array.from(main.querySelectorAll("div"));
    return divs.find((el) => getComputedStyle(el).overflowY === "auto")!;
  });
}

function distanceFromBottom(scroller: JSHandle<HTMLDivElement>) {
  return scroller.evaluate((el) => {
    return el.scrollHeight - el.scrollTop - el.clientHeight;
  });
}

test("hovering a reply shows its time, and Copy puts the reply on the clipboard", async ({
  page,
  context,
}) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.goto("/chat");
  await startConversation(page, "Thread journey: copy this reply");

  const main = page.getByRole("main");
  const reply = main.getByText(REPLY, { exact: true });
  // DOM order: the user turn's time, then the reply's.
  const time = main.locator("time").nth(1);
  const slot = time.locator("..");
  await expect(time).toHaveText(/\d/);
  await expect(slot).toHaveCSS("opacity", "0");

  await reply.hover();
  await expect(slot).toHaveCSS("opacity", "1");

  await slot.getByRole("button", { name: "Copy message" }).click();
  const copied = await page.evaluate(() => navigator.clipboard.readText());
  expect(copied).toBe(REPLY);
});

test("the view follows a streaming reply, and scrolling up mid-stream stops it", async ({
  page,
}) => {
  await page.goto("/chat");
  await composer(page).fill(TALL_TEXT);
  await composer(page).press("Enter");
  const main = page.getByRole("main");
  await expect(main.getByText(REPLY, { exact: true })).toBeVisible();
  await expect(page).toHaveURL(/\/chat\/[^/]+$/);

  const scroller = await threadScroller(page);
  const overflow = await scroller.evaluate((el) => {
    return el.scrollHeight - el.clientHeight;
  });
  expect(overflow).toBeGreaterThan(400);

  await composer(page).fill(SLOW_TEXT);
  await composer(page).press("Enter");
  await expect(main.getByText("Slowly streaming reply, part 2.")).toBeVisible();
  await expect.poll(() => distanceFromBottom(scroller)).toBeLessThan(3);
  await expect(main.getByText("Slowly streaming reply, part 4.")).toBeVisible();
  await expect.poll(() => distanceFromBottom(scroller)).toBeLessThan(3);

  // Retried in case a piece's re-pin lands before the browser fires the
  // scroll event that releases the follow.
  await expect(async () => {
    await scroller.evaluate(async (el) => {
      el.scrollTop = el.scrollHeight - el.clientHeight - 200;
      await new Promise((resolve) => {
        requestAnimationFrame(() => requestAnimationFrame(resolve));
      });
    });
    const released = await distanceFromBottom(scroller);
    expect(released).toBeGreaterThan(STICK_THRESHOLD_PX);
  }).toPass();
  const releasedAt = await scroller.evaluate((el) => el.scrollTop);
  await expect(main.getByText("Slowly streaming reply, part 10.")).toHaveCount(
    0,
  );

  await expect(
    main.getByText("Slowly streaming reply, part 10."),
  ).toBeVisible();
  const top = await scroller.evaluate((el) => el.scrollTop);
  expect(Math.abs(top - releasedAt)).toBeLessThan(3);
  const after = await distanceFromBottom(scroller);
  expect(after).toBeGreaterThan(STICK_THRESHOLD_PX);
});
