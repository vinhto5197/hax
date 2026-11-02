import {
  expect,
  test,
  type JSHandle,
  type Page,
  type TestInfo,
} from "@playwright/test";
import {
  composer,
  distanceFromBottom,
  REPLY,
  send,
  startConversation,
  threadScroller,
} from "./chat";

const DESKTOP = { width: 1280, height: 800 };
const PHONE = { width: 390, height: 844 };
// Mirrors STICK_THRESHOLD_PX in components/chat/MessageList.tsx.
const STICK_THRESHOLD_PX = 64;

test.use({ viewport: DESKTOP });

function jumpButton(page: Page) {
  return page.getByRole("button", { name: "Jump to latest" });
}

// A user bubble keeps its line breaks, so one tall turn makes the thread
// scroll at both viewports. The label keeps each journey's text unique.
function tallText(label: string) {
  const lines = Array.from({ length: 40 }, (_, i) => `Jump line ${i + 1}`);
  return `Jump journey: ${label}\n${lines.join("\n")}`;
}

// Sends a tall first turn from the new-chat screen and waits for its reply and
// the conversation URL; never waits on the sidebar row (a phone has none).
async function tallConversation(page: Page, label: string) {
  await page.goto("/chat");
  await composer(page).fill(tallText(label));
  await composer(page).press("Enter");
  const main = page.getByRole("main");
  await expect(main.getByText(REPLY, { exact: true })).toBeVisible();
  await expect(page).toHaveURL(/\/chat\/[^/]+$/);
  const scroller = await threadScroller(page);
  const overflow = await scroller.evaluate((el) => {
    return el.scrollHeight - el.clientHeight;
  });
  expect(overflow).toBeGreaterThan(300);
  return scroller;
}

// Scrolls the thread to `px` above its bottom and waits two frames for the
// scroll event. Retried in case a streamed piece's re-pin lands before the
// browser fires the scroll event that releases the follow.
async function scrollAboveBottom(
  scroller: JSHandle<HTMLDivElement>,
  px: number,
) {
  await expect(async () => {
    await scroller.evaluate(async (el, offset) => {
      el.scrollTop = el.scrollHeight - el.clientHeight - offset;
      await new Promise((resolve) => {
        requestAnimationFrame(() => requestAnimationFrame(resolve));
      });
    }, px);
    const distance = await distanceFromBottom(scroller);
    expect(Math.abs(distance - px)).toBeLessThan(3);
  }).toPass();
}

async function releaseFollow(scroller: JSHandle<HTMLDivElement>) {
  await scrollAboveBottom(scroller, 200);
  expect(await distanceFromBottom(scroller)).toBeGreaterThan(
    STICK_THRESHOLD_PX,
  );
}

function scrollerBox(scroller: JSHandle<HTMLDivElement>) {
  return scroller.evaluate((el) => {
    const r = el.getBoundingClientRect();
    return { x: r.x, y: r.y, width: r.width, height: r.height };
  });
}

async function shot(page: Page, testInfo: TestInfo, name: string) {
  const path = testInfo.outputPath(`${name}.png`);
  await page.screenshot({ path });
  await testInfo.attach(name, { path, contentType: "image/png" });
}

test("Jump to latest is absent when the view is at the bottom: a short conversation, and a long one just opened", async ({
  page,
}) => {
  await page.goto("/chat");
  await startConversation(page, "Jump journey: a short turn");
  await expect(jumpButton(page)).toHaveCount(0);

  const main = page.getByRole("main");
  const tall = tallText("a long one just opened");
  await composer(page).fill(tall);
  await composer(page).press("Enter");
  await expect(main.getByText(REPLY, { exact: true })).toHaveCount(2);

  await page.reload();
  await expect(main.getByText(REPLY, { exact: true })).toHaveCount(2);
  const scroller = await threadScroller(page);
  await expect.poll(() => distanceFromBottom(scroller)).toBeLessThan(3);
  await expect(jumpButton(page)).toHaveCount(0);
});

test("Scrolling up shows Jump to latest over the bottom of the thread, and scrolling back down hides it", async ({
  page,
}) => {
  const scroller = await tallConversation(page, "scroll up and back down");
  await releaseFollow(scroller);

  const button = jumpButton(page);
  await expect(button).toBeVisible();
  const box = (await button.boundingBox())!;
  const area = await scrollerBox(scroller);
  const buttonCentre = box.x + box.width / 2;
  const areaCentre = area.x + area.width / 2;
  expect(Math.abs(buttonCentre - areaCentre)).toBeLessThan(2);
  const gap = area.y + area.height - (box.y + box.height);
  expect(Math.abs(gap - 16)).toBeLessThanOrEqual(2);
  const textbox = (await composer(page).boundingBox())!;
  expect(box.y + box.height).toBeLessThanOrEqual(textbox.y);

  await scrollAboveBottom(scroller, 30);
  await expect(button).toHaveCount(0);
});

test("Jump to latest during a streaming reply brings the newest text into view and the view follows again", async ({
  page,
}) => {
  const scroller = await tallConversation(page, "press while streaming");
  const main = page.getByRole("main");

  await send(page, "slow: jump journey, press while streaming");
  await expect(main.getByText("Slowly streaming reply, part 2.")).toBeVisible();
  await releaseFollow(scroller);
  await expect(jumpButton(page)).toBeVisible();

  await jumpButton(page).click();
  await expect.poll(() => distanceFromBottom(scroller)).toBeLessThan(3);
  await expect(jumpButton(page)).toHaveCount(0);

  await expect(
    main.getByText("Slowly streaming reply, part 10."),
  ).toBeVisible();
  await expect.poll(() => distanceFromBottom(scroller)).toBeLessThan(3);
});

test("Scrolling up again after Jump to latest releases the follow and shows the button again", async ({
  page,
}) => {
  test.setTimeout(60_000);
  const scroller = await tallConversation(page, "scroll up after the press");
  const main = page.getByRole("main");

  // The long reply's ten seconds leave room for the press, the smooth scroll
  // and two releases before its last piece arrives.
  await send(page, "long: jump journey, scroll up after the press");
  await expect(main.getByText("Long reply, part 2.")).toBeVisible();
  await releaseFollow(scroller);
  await jumpButton(page).click();
  await expect.poll(() => distanceFromBottom(scroller)).toBeLessThan(3);

  await releaseFollow(scroller);
  await expect(jumpButton(page)).toBeVisible();
  const releasedAt = await scroller.evaluate((el) => el.scrollTop);
  await expect(main.getByText("Long reply, part 20.")).toHaveCount(0);

  await expect(main.getByText("Long reply, part 20.")).toBeVisible({
    timeout: 15_000,
  });
  const top = await scroller.evaluate((el) => el.scrollTop);
  expect(Math.abs(top - releasedAt)).toBeLessThan(3);
  await expect(jumpButton(page)).toBeVisible();
});

test("Sending a message while scrolled up brings the view to the bottom and hides Jump to latest", async ({
  page,
}) => {
  const scroller = await tallConversation(page, "send while scrolled up");
  const main = page.getByRole("main");
  await releaseFollow(scroller);
  await expect(jumpButton(page)).toBeVisible();

  const question = "Jump journey: a short question sent while scrolled up";
  await send(page, question);
  await expect(main.getByText(REPLY, { exact: true })).toHaveCount(2);
  await expect(main.getByText(question, { exact: true })).toBeInViewport();
  await expect(main.getByText(REPLY, { exact: true }).last()).toBeInViewport();
  await expect.poll(() => distanceFromBottom(scroller)).toBeLessThan(3);
  await expect(jumpButton(page)).toHaveCount(0);
});

test("With reduced motion, Jump to latest lands at the bottom at once", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  const scroller = await tallConversation(page, "reduced motion");
  await releaseFollow(scroller);
  await expect(jumpButton(page)).toBeVisible();

  // Pressed and measured inside one evaluate: a smooth scroll would still be
  // under way two frames after the press.
  const distance = await scroller.evaluate(async (el) => {
    const button = document.querySelector<HTMLButtonElement>(
      'button[aria-label="Jump to latest"]',
    )!;
    button.click();
    await new Promise((resolve) => {
      requestAnimationFrame(() => requestAnimationFrame(resolve));
    });
    return el.scrollHeight - el.scrollTop - el.clientHeight;
  });
  expect(distance).toBeLessThan(3);
});

test.describe("phone", () => {
  test.use({ viewport: PHONE });

  test("At phone width Jump to latest sits inside the screen above the composer", async ({
    page,
  }) => {
    const scroller = await tallConversation(page, "phone width");
    await releaseFollow(scroller);

    const button = jumpButton(page);
    await expect(button).toBeVisible();
    const box = (await button.boundingBox())!;
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(PHONE.width);
    const textbox = (await composer(page).boundingBox())!;
    expect(box.y + box.height).toBeLessThanOrEqual(textbox.y);
  });
});

test("Jump to latest looks right in both themes at desktop and phone width", async ({
  page,
}, testInfo) => {
  const scroller = await tallConversation(page, "screenshots");

  for (const [width, viewport] of [
    ["desktop", DESKTOP],
    ["phone", PHONE],
  ] as const) {
    await page.setViewportSize(viewport);
    await releaseFollow(scroller);
    await expect(jumpButton(page)).toBeVisible();
    for (const colorScheme of ["light", "dark"] as const) {
      await page.emulateMedia({ colorScheme });
      await expect(jumpButton(page)).toBeVisible();
      await shot(page, testInfo, `jump-to-latest-${width}-${colorScheme}`);
    }
  }
});
