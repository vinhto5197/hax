import { expect, test } from "@playwright/test";

test("a signed-in member stays on /chat", async ({ page }) => {
  await page.goto("/chat");
  await expect(page).toHaveURL(/\/chat$/);
  await expect(page.getByPlaceholder("Type your prompt...")).toBeVisible();
});
