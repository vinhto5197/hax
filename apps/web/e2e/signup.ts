import type { Page } from "@playwright/test";

// The specs run in parallel against one database: each spec passes its own
// prefix, so two specs never mint the same address in the same millisecond.
export function uniqueEmail(prefix: string, label: string) {
  return `${prefix}-${label}-${Date.now()}@example.com`;
}

// Fills the signup form and submits it; the caller asserts what follows.
export async function fillSignup(
  page: Page,
  email: string,
  password: string,
  name: string,
) {
  await page.goto("/signup");
  await page.getByPlaceholder("Name").fill(name);
  await page.getByPlaceholder("Email").fill(email);
  await page.getByPlaceholder("Password (8+ characters)").fill(password);
  await page.getByRole("button", { name: "Sign up", exact: true }).click();
}
