import {
  expect,
  type JSHandle,
  type Page,
  type TestInfo,
} from "@playwright/test";

export const REPLY = "Hello from the fake model.";
export const SLOW_REPLY = "Slowly streaming reply";
// A "long:" prompt's whole reply: twenty "Long reply, part N. " deltas
// (fake-model/server.mjs).
export const LONG_REPLY = Array.from(
  { length: 20 },
  (_, i) => `Long reply, part ${i + 1}. `,
)
  .join("")
  .trim();
export const INTERRUPTED = "The reply was interrupted.";
export const BUSY = "A reply is already in progress in this conversation.";
export const DESKTOP = { width: 1280, height: 800 };
export const PHONE = { width: 390, height: 844 };

export function composer(page: Page) {
  // By name, not placeholder: the placeholder differs for a visitor.
  return page.getByRole("textbox", { name: "Message" });
}

export function sendButton(page: Page) {
  return page.getByRole("button", { name: "Send", exact: true });
}

export function stopButton(page: Page) {
  return page.getByRole("button", { name: "Stop" });
}

// Scoped to the chat: Next.js renders an empty role="alert" route announcer
// outside it on every page.
export function errorLine(page: Page) {
  return page.getByRole("main").getByRole("alert");
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

// The thread's scroll container has no role or label: it is the first
// scrollable element in main, ahead of the composer.
export async function threadScroller(page: Page) {
  return page.getByRole("main").evaluateHandle((main) => {
    const divs = Array.from(main.querySelectorAll("div"));
    return divs.find((el) => getComputedStyle(el).overflowY === "auto")!;
  });
}

export function distanceFromBottom(scroller: JSHandle<HTMLDivElement>) {
  return scroller.evaluate((el) => {
    return el.scrollHeight - el.scrollTop - el.clientHeight;
  });
}

export async function shot(page: Page, testInfo: TestInfo, name: string) {
  const path = testInfo.outputPath(`${name}.png`);
  await page.screenshot({ path });
  await testInfo.attach(name, { path, contentType: "image/png" });
}
