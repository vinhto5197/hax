import { expect, test } from "@playwright/test";

// Google is never contacted: the stack's Google client is a placeholder
// (playwright.config.ts), and the flow is held at its first request anyway.
test("the Google button reads Redirecting… and is disabled while sign-in is under way", async ({
  page,
}) => {
  await page.route(/accounts\.google\.com/, (route) => route.abort());
  let release!: () => void;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  let posts = 0;
  // NextAuth's signIn("google") posts here before any redirect to Google.
  await page.route("**/auth/signin/google**", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    posts += 1;
    await held;
    await route.abort();
  });

  await page.goto("/login");
  const button = page.getByRole("button", { name: "Continue with Google" });
  await button.click();

  const busy = page.getByRole("button", { name: "Redirecting…" });
  await expect(busy).toBeVisible();
  await expect(busy).toBeDisabled();
  await expect.poll(() => posts).toBe(1);

  release();
});

// Without it, Google signs the browser's only Google session straight back in
// after a logout, and the user cannot switch accounts.
test("Continue with Google asks Google to show its account chooser", async ({
  page,
}) => {
  let googleUrl: URL | null = null;
  await page.route(/accounts\.google\.com/, (route) => {
    googleUrl = new URL(route.request().url());
    return route.abort();
  });

  await page.goto("/login");
  await page.getByRole("button", { name: "Continue with Google" }).click();

  await expect
    .poll(() => googleUrl?.searchParams.get("prompt"))
    .toBe("select_account");
});
