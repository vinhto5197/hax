import { expect, type Page } from "@playwright/test";
import { composer, PHONE } from "./chat";

// A touch phone as Chromium emulates one: no hover, a coarse pointer, touch
// events. The app's `touch:` variant is `@media (hover: none)`.
export const TOUCH_PHONE = { viewport: PHONE, hasTouch: true, isMobile: true };

// How long a negative focus check watches before it is believed: a focus call
// from an effect lands within a frame or two of the render that schedules it.
const SETTLE_MS = 1000;

// Records every time the composer gains focus, from the first script on the
// page, so a focus that is given and then lost again still counts. Call
// before the first navigation.
export async function watchComposerFocus(page: Page) {
  await page.addInitScript(() => {
    const w = window as unknown as { __composerFocusCount: number };
    w.__composerFocusCount = 0;
    document.addEventListener(
      "focusin",
      (event) => {
        const target = event.target as Element | null;
        if (target?.matches?.('textarea[aria-label="Message"]')) {
          w.__composerFocusCount += 1;
        }
      },
      true,
    );
  });
}

export async function resetComposerFocusCount(page: Page) {
  await page.evaluate(() => {
    (
      window as unknown as { __composerFocusCount: number }
    ).__composerFocusCount = 0;
  });
}

export async function expectTouchDevice(page: Page) {
  const media = await page.evaluate(() => ({
    hoverNone: matchMedia("(hover: none)").matches,
    coarse: matchMedia("(pointer: coarse)").matches,
  }));
  expect(media).toEqual({ hoverNone: true, coarse: true });
}

// The composer is not focused now, and was not focused at any moment since
// the count was last reset, over a settle window.
export async function expectComposerNeverFocused(page: Page) {
  await page.waitForTimeout(SETTLE_MS);
  await expect(composer(page)).not.toBeFocused();
  const count = await page.evaluate(
    () =>
      (window as unknown as { __composerFocusCount: number })
        .__composerFocusCount,
  );
  expect(count, "times the message box gained focus").toBe(0);
}
