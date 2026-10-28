import { expect, type Page } from "@playwright/test";

export const REPLY = "Hello from the fake model.";
export const SLOW_REPLY = "Slowly streaming reply";

export function composer(page: Page) {
  // By name, not placeholder: the placeholder differs for a visitor.
  return page.getByRole("textbox", { name: "Message" });
}

export async function send(page: Page, text: string) {
  await composer(page).fill(text);
  await composer(page).press("Enter");
}

export function sidebarLink(page: Page, path: string) {
  return page.getByRole("navigation").locator(`a[href="${path}"]`);
}

// From the new-chat screen: sends the first message, waits for the reply and
// the conversation URL, and returns that URL's path.
export async function startConversation(page: Page, text: string) {
  await expect(page).toHaveURL(/\/chat$/);
  await send(page, text);
  const main = page.getByRole("main");
  await expect(main.getByText(text, { exact: true })).toBeVisible();
  await expect(main.getByText(REPLY, { exact: true })).toBeVisible();
  await expect(page).toHaveURL(/\/chat\/[^/]+$/);
  const path = new URL(page.url()).pathname;
  await expect(sidebarLink(page, path)).toBeVisible();
  return path;
}

export async function openNewChat(page: Page) {
  await page.getByRole("link", { name: "+ New chat", exact: true }).click();
  await expect(page).toHaveURL(/\/chat$/);
}
