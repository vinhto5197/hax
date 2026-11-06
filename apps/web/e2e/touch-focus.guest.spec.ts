import { expect, test } from "@playwright/test";
import { composer } from "./chat";
import {
  expectComposerNeverFocused,
  expectTouchDevice,
  TOUCH_PHONE,
  watchComposerFocus,
} from "./touch";

// The seeded member (e2e/prepare.py, auth.setup.ts). Signing in again issues
// a new session and revokes none, so the member project's stored session
// stays valid.
const EMAIL = "e2e@example.com";
const PASSWORD = "e2e-password-123";

test.use(TOUCH_PHONE);

test("on a touch phone, a password login that lands on /chat leaves the message box unfocused", async ({
  page,
}) => {
  await watchComposerFocus(page);
  await page.goto("/login");
  await expectTouchDevice(page);
  await page.getByPlaceholder("Email").fill(EMAIL);
  await page.getByPlaceholder("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Log in", exact: true }).tap();

  await expect(page).toHaveURL(/\/chat$/);
  await expect(composer(page)).toBeEnabled();
  await expectComposerNeverFocused(page);
});
