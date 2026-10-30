import { expect, test } from "@playwright/test";

// A phone held sideways: desktop width, but at most 500px tall, which the
// shell treats as a phone.
test.use({ viewport: { width: 844, height: 480 } });

test("at 844x480 the top bar has the menu, the wordmark and +, and no sidebar", async ({
  page,
}) => {
  await page.goto("/chat");

  await expect(page.getByRole("button", { name: "Open menu" })).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Hax home", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "New chat", exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("navigation")).toHaveCount(0);
  await expect(page.getByRole("link", { name: "+ New chat" })).toHaveCount(0);
});

test("at 844x480 the menu opens the drawer with the conversation list", async ({
  page,
}) => {
  await page.goto("/chat");
  await page.getByRole("button", { name: "Open menu" }).click();

  const drawer = page.getByRole("dialog", { name: "Menu" });
  await expect(drawer).toBeVisible();
  await expect(drawer.getByRole("navigation")).toBeVisible();
});
