import { expect, test } from "@playwright/test";
import { REPLY, send } from "./chat";

test("/chat with no session redirects to /login", async ({ page }) => {
  await page.goto("/chat");

  await expect(page).toHaveURL(/\/login$/);
  const heading = page.getByRole("heading", {
    name: "Log in to Hax",
    exact: true,
  });
  await expect(heading).toBeVisible();
});

test("a demo visitor at /chat is sent back to /", async ({ page }) => {
  await page.goto("/");
  await send(page, "Routing journey: start a demo session");
  const main = page.getByRole("main");
  await expect(main.getByText(REPLY, { exact: true })).toBeVisible();

  await page.goto("/chat");
  await expect(page).toHaveURL(/^http:\/\/[^/]+\/$/);
});

test("the privacy page renders without a session and has a mailto link", async ({
  page,
}) => {
  await page.goto("/privacy");

  await expect(page).toHaveURL(/\/privacy$/);
  const heading = page.getByRole("heading", { level: 1, name: "Privacy" });
  await expect(heading).toBeVisible();
  const contact = page.locator('a[href^="mailto:"]');
  await expect(contact).toHaveCount(1);
  await expect(contact).toBeVisible();
});
