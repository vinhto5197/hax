import { expect, test, type Page } from "@playwright/test";
import { composer, sendButton } from "./chat";
import {
  expectComposerNeverFocused,
  expectTouchDevice,
  resetComposerFocusCount,
  TOUCH_PHONE,
  watchComposerFocus,
} from "./touch";

// On a touch device a focused message box raises the on-screen keyboard over
// the thread, so the composer never focuses itself there; a tap is the only
// way in. The desktop half of the contract (focus returns after a reply) is
// pinned by chat-basics.member.spec.ts's "Send is disabled when empty; ...
// focus returns after".
const SLOW_TEXT = "slow: touch focus journey, the composer after a reply";

test.use(TOUCH_PHONE);

test.beforeEach(async ({ page }) => {
  await watchComposerFocus(page);
});

function aboutYouDialog(page: Page) {
  return page.getByRole("dialog", { name: "About you" });
}

async function openAboutYouFromDrawer(page: Page) {
  await page.getByRole("button", { name: "Open menu" }).tap();
  const drawer = page.getByRole("dialog", { name: "Menu" });
  await expect(drawer).toBeVisible();
  await drawer.getByRole("button", { name: "Account menu" }).tap();
  await drawer.getByText("About you", { exact: true }).tap();
  await expect(aboutYouDialog(page)).toBeVisible();
  // The textarea is disabled until the saved note has loaded.
  await expect(
    aboutYouDialog(page).getByRole("textbox", { name: "About you" }),
  ).toBeEnabled();
}

test("on a touch phone, /chat on first load leaves the message box unfocused", async ({
  page,
}) => {
  await page.goto("/chat");
  await expectTouchDevice(page);
  await expect(composer(page)).toBeEnabled();
  await expectComposerNeverFocused(page);
});

test("on a touch phone, the message box stays unfocused when it re-enables after a reply", async ({
  page,
}) => {
  await page.goto("/chat");
  await expectTouchDevice(page);
  await composer(page).fill(SLOW_TEXT);
  // A tap on Send moves focus off the message box, so any focus after this
  // is the app's own.
  await sendButton(page).tap();
  await expect(composer(page)).toBeDisabled();
  await resetComposerFocusCount(page);

  const main = page.getByRole("main");
  await expect(
    main.getByText("Slowly streaming reply, part 10."),
  ).toBeVisible();
  await expect(composer(page)).toBeEnabled();
  await expectComposerNeverFocused(page);
});

test("on a touch phone, closing About you with Escape leaves the message box unfocused", async ({
  page,
}) => {
  await page.goto("/chat");
  await expectTouchDevice(page);
  await openAboutYouFromDrawer(page);
  await resetComposerFocusCount(page);

  await page.keyboard.press("Escape");
  await expect(aboutYouDialog(page)).toHaveCount(0);
  await expectComposerNeverFocused(page);
});

test("on a touch phone, closing About you with Cancel leaves the message box unfocused", async ({
  page,
}) => {
  await page.goto("/chat");
  await expectTouchDevice(page);
  await openAboutYouFromDrawer(page);
  await resetComposerFocusCount(page);

  await aboutYouDialog(page).getByRole("button", { name: "Cancel" }).tap();
  await expect(aboutYouDialog(page)).toHaveCount(0);
  await expectComposerNeverFocused(page);
});
