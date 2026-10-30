import { expect, test, type Page } from "@playwright/test";

import { mailLink } from "./mail";

// Each test signs up its own address and reads the link the API mailed to it
// from Mailpit; never the seeded member, whose reset would revoke the
// sessions every member journey runs on.
const INVALID_LINK = "This link is invalid or has expired.";
const VERIFIED_BANNER = "Email verified — log in to continue.";

function uniqueEmail(label: string) {
  return `mail-${label}-${Date.now()}@example.com`;
}

async function signUp(page: Page, email: string, password: string) {
  await page.goto("/signup");
  await page.getByPlaceholder("Name").fill("Mail Journey");
  await page.getByPlaceholder("Email").fill(email);
  await page.getByPlaceholder("Password (8+ characters)").fill(password);
  await page.getByRole("button", { name: "Sign up", exact: true }).click();
  const inbox = page.getByRole("heading", { name: "Check your inbox" });
  await expect(inbox).toBeVisible();
}

test("row 55: signing up sends a verification link, and Confirm on it lands on /login?verified=1 with the email prefilled", async ({
  page,
  request,
}) => {
  test.setTimeout(60_000);
  const email = uniqueEmail("verify");
  await signUp(page, email, "mail-verify-password");

  const link = await mailLink(request, email, "/verify-email");
  expect(link.startsWith("http://localhost:3001/verify-email?token=")).toBe(
    true,
  );
  expect(link).toMatch(/\?token=\S+$/);

  await page.goto(link);
  await expect(page.getByText("Confirm your email")).toBeVisible();
  await page.getByRole("button", { name: "Confirm", exact: true }).click();

  await expect(page).toHaveURL(/\/login\?verified=1&email=/);
  const landed = new URL(page.url());
  expect(landed.pathname).toBe("/login");
  expect(landed.searchParams.get("verified")).toBe("1");
  expect(landed.searchParams.get("email")).toBe(email);
  await expect(page.getByText(VERIFIED_BANNER)).toBeVisible();
  await expect(page.getByPlaceholder("Email")).toHaveValue(email);
});

test("row 57: a reset link from the email opens the new-password form; saving a new password signs in and lands on /chat, and the spent link then shows the invalid view", async ({
  page,
  request,
}) => {
  test.setTimeout(60_000);
  const email = uniqueEmail("reset");
  await signUp(page, email, "mail-reset-old-password");

  await page.goto("/forgot-password");
  await page.getByPlaceholder("Email").fill(email);
  await page.getByRole("button", { name: "Send reset link" }).click();
  const inbox = page.getByRole("heading", { name: "Check your inbox" });
  await expect(inbox).toBeVisible();

  const link = await mailLink(request, email, "/reset-password");
  expect(link.startsWith("http://localhost:3001/reset-password?token=")).toBe(
    true,
  );
  expect(link).toMatch(/\?token=\S+$/);

  await page.goto(link);
  await expect(page.getByText("Choose a new password")).toBeVisible();
  await expect(page.getByText(INVALID_LINK)).toHaveCount(0);
  await page
    .getByPlaceholder("New password (8+ characters)")
    .fill("mail-reset-new-password");
  await page.getByRole("button", { name: "Save new password" }).click();

  await expect(page).toHaveURL(/\/chat(?:[/?#]|$)/);

  // Revisited signed in, with the session the reset created.
  await page.goto(link);
  await expect(page.getByText(INVALID_LINK)).toBeVisible();
  const again = page.getByRole("link", { name: "Request a new link" });
  await expect(again).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Save new password" }),
  ).toHaveCount(0);
});
