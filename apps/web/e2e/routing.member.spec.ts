import { expect, test } from "@playwright/test";

// The seeded member (e2e/prepare.py).
const NAME = "E2E";
const EMAIL = "e2e@example.com";

test("a member at /, /login and /signup lands on /chat", async ({ page }) => {
  for (const path of ["/", "/login", "/signup"]) {
    await page.goto(path);
    await expect(page).toHaveURL(/\/chat$/);
    await expect(page.getByRole("link", { name: "+ New chat" })).toBeVisible();
  }
});

// Signs this test's context out, so it stays last in the file and alone in
// its block: no later test may reuse the signed-out state.
test.describe.serial("account block", () => {
  test("shows the member's name and email, and Sign out lands on /", async ({
    page,
  }) => {
    await page.goto("/chat");
    const sidebar = page.getByRole("complementary");
    await expect(sidebar.getByText(NAME, { exact: true })).toBeVisible();
    await expect(sidebar.getByText(EMAIL, { exact: true })).toBeVisible();

    await sidebar.getByRole("button", { name: "Sign out" }).click();
    await expect(page).toHaveURL(/^http:\/\/[^/]+\/$/);
    const logIn = page.getByRole("link", { name: "Log in", exact: true });
    await expect(logIn).toBeVisible();
    await expect(page.getByRole("button", { name: "Sign out" })).toHaveCount(0);
  });
});
