import { expect, test, type Page } from "@playwright/test";

// Every accepted signup and reset request spends a shared per-IP budget (10
// an hour each in apps/api/routers/auth.py); a 422 is refused before the
// limiter runs.
const INVALID_LINK = "This link is invalid or has expired.";
const EMAIL_RULE = "Please enter a valid email address.";
// Passes the browser's type=email check but not the API's EmailStr.
const BAD_EMAIL = "a@b";
// Seeded by e2e/prepare.py; only ever asked for a reset link here.
const MEMBER_EMAIL = "e2e@example.com";

function uniqueEmail(label: string) {
  return `signup-${label}-${Date.now()}@example.com`;
}

async function fillSignup(page: Page, email: string, password: string) {
  await page.goto("/signup");
  await page.getByPlaceholder("Name").fill("Signup Journey");
  await page.getByPlaceholder("Email").fill(email);
  await page.getByPlaceholder("Password (8+ characters)").fill(password);
  await page.getByRole("button", { name: "Sign up", exact: true }).click();
}

function inboxHeading(page: Page) {
  return page.getByRole("heading", { name: "Check your inbox" });
}

test("signup with an address the API rejects shows the email message", async ({
  page,
}) => {
  await fillSignup(page, BAD_EMAIL, "signup-journey-password");

  await expect(page.getByText(EMAIL_RULE)).toBeVisible();
  await expect(inboxHeading(page)).toHaveCount(0);
});

test("signup with a short password is stopped before any request", async ({
  page,
}) => {
  const requests: string[] = [];
  page.on("request", (request) => {
    const url = request.url();
    if (url.includes("/api/auth/signup")) requests.push(url);
  });

  await fillSignup(page, uniqueEmail("short"), "short");

  const password = page.getByPlaceholder("Password (8+ characters)");
  const tooShort = () =>
    password.evaluate((el) => (el as HTMLInputElement).validity.tooShort);
  await expect.poll(tooShort).toBe(true);
  const form = page.getByRole("heading", { name: "Sign up for hax" });
  await expect(form).toBeVisible();
  expect(requests).toEqual([]);
});

test("a valid signup shows the check-your-inbox panel with the address", async ({
  page,
}) => {
  const email = uniqueEmail("valid");
  await fillSignup(page, email, "signup-journey-password");

  await expect(inboxHeading(page)).toBeVisible();
  await expect(
    page.getByText(`We sent a verification link to ${email}.`),
  ).toBeVisible();
  const back = page.getByRole("link", { name: "Back to log in" });
  await expect(back).toHaveAttribute("href", "/login");
});

test("Resend on the check-your-inbox panel shows the sent status", async ({
  page,
}) => {
  await fillSignup(page, uniqueEmail("resend"), "signup-journey-password");
  await expect(inboxHeading(page)).toBeVisible();

  await page.getByRole("button", { name: "Didn't get it? Resend" }).click();
  await expect(page.getByText("Sent.", { exact: true })).toBeVisible();
});

async function requestReset(page: Page, email: string) {
  await page.goto("/forgot-password");
  await page.getByPlaceholder("Email").fill(email);
  await page.getByRole("button", { name: "Send reset link" }).click();
}

test("forgot password shows the same panel for a registered and an unknown email", async ({
  page,
}) => {
  for (const email of [MEMBER_EMAIL, uniqueEmail("unknown")]) {
    await requestReset(page, email);
    await expect(inboxHeading(page)).toBeVisible();
    await expect(
      page.getByText(`If an account exists for ${email}, we've sent`),
    ).toBeVisible();
  }
});

test("forgot password with an address the API rejects shows the email message", async ({
  page,
}) => {
  await requestReset(page, BAD_EMAIL);

  await expect(page.getByText(EMAIL_RULE)).toBeVisible();
  await expect(inboxHeading(page)).toHaveCount(0);
});

function confirmButton(page: Page) {
  return page.getByRole("button", { name: "Confirm", exact: true });
}

function newLinkButton(page: Page) {
  return page.getByRole("button", { name: "Send a new link" });
}

test("/verify-email with no token shows the invalid view", async ({ page }) => {
  await page.goto("/verify-email");

  await expect(page.getByText(INVALID_LINK)).toBeVisible();
  await expect(newLinkButton(page)).toBeVisible();
  await expect(confirmButton(page)).toHaveCount(0);
});

test("/verify-email with a bad token waits for Confirm, then shows the resend form", async ({
  page,
}) => {
  await page.goto("/verify-email?token=not-a-real-token");

  const confirm = confirmButton(page);
  await expect(confirm).toBeVisible();
  await expect(page.getByText(INVALID_LINK)).toHaveCount(0);

  await confirm.click();
  await expect(page.getByText(INVALID_LINK)).toBeVisible();
  await expect(page.getByPlaceholder("Email")).toBeVisible();
  await expect(newLinkButton(page)).toBeVisible();
  await expect(page).toHaveURL(/\/verify-email\?token=not-a-real-token$/);
});

test("/reset-password with a bad token shows Checking your link, then the invalid view", async ({
  page,
}) => {
  // Holds the precheck so the checking state stays on screen to be seen.
  let release = () => {};
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/auth/reset-password/check", async (route) => {
    await held;
    await route.continue();
  });

  await page.goto("/reset-password?token=not-a-real-token");
  await expect(page.getByText("Checking your link…")).toBeVisible();

  release();
  await expect(page.getByText(INVALID_LINK)).toBeVisible();
  await expect(page.getByText("Checking your link…")).toHaveCount(0);
  const again = page.getByRole("link", { name: "Request a new link" });
  await expect(again).toHaveAttribute("href", "/forgot-password");
  const save = page.getByRole("button", { name: "Save new password" });
  await expect(save).toHaveCount(0);
});

test.fixme(
  "reset form validation and success → /chat: needs a real reset token, which never reaches a journey",
  async () => {},
);
