import { expect, test } from "@playwright/test";

test("a guest gets the fake model's reply", async ({ page }) => {
  await page.goto("/");
  const composer = page.getByPlaceholder("Type your prompt...");
  await composer.fill("hi");
  await composer.press("Enter");
  await expect(page.getByText("Hello from the fake model.")).toBeVisible();
});
