import { expect, test as setup } from "@playwright/test";

// The member seeded by e2e/prepare.py; the two must change together.
const EMAIL = "e2e@example.com";
const PASSWORD = "e2e-password-123";

setup("sign in the seeded member", async ({ page }) => {
  await page.goto("/login");
  await page.getByPlaceholder("Email").fill(EMAIL);
  await page.getByPlaceholder("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Log in", exact: true }).click();
  await expect(page).not.toHaveURL(/\/login/);
  await page.context().storageState({ path: "e2e/.auth/member.json" });
});
