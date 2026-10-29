import { expect, test, type Page, type Request } from "@playwright/test";
import {
  composer,
  openNewChat,
  REPLY,
  send,
  sidebarLink,
  startConversation,
} from "./chat";

const SLOW_TEXT = "slow: basics journey, the composer while streaming";
const NO_CONVERSATIONS = "No conversations yet. Start one above.";
// The fake model refuses every title unless the first message starts with
// "title:", so every conversation here stays untitled.
const CONFIRM = `Delete "this conversation"? This can't be undone.`;
// The non-default ids ModelSelect.tsx offers; the API's allowlist is ModelId
// in packages/core/schemas/chat.py.
const PICKED_MODEL = "claude-sonnet-4-6";

function isChat(request: Request) {
  return request.url().endsWith("/api/chat") && request.method() === "POST";
}

function sendButton(page: Page) {
  return page.getByRole("button", { name: "Send", exact: true });
}

// The row is the div holding the conversation's link; a `has` locator is
// resolved inside that div, so it cannot be rooted at the navigation.
function deleteButton(page: Page, path: string) {
  return page
    .getByRole("navigation")
    .locator("div")
    .filter({ has: page.locator(`a[href="${path}"]`) })
    .getByRole("button", { name: /^Delete / });
}

test("Shift+Enter adds a line without sending; Enter then sends both lines", async ({
  page,
}) => {
  const first = "Basics journey: line one";
  const second = "Basics journey: line two";
  const chatRequests: Request[] = [];
  page.on("request", (request) => {
    if (isChat(request)) chatRequests.push(request);
  });

  await page.goto("/chat");
  await composer(page).fill(first);
  await composer(page).press("Shift+Enter");
  await composer(page).pressSequentially(second);
  await expect(composer(page)).toHaveValue(`${first}\n${second}`);
  expect(chatRequests).toEqual([]);
  await expect(page).toHaveURL(/\/chat$/);

  const request = page.waitForRequest(isChat);
  await composer(page).press("Enter");
  expect((await request).postDataJSON().prompt).toBe(`${first}\n${second}`);

  const main = page.getByRole("main");
  await expect(main.getByText(first)).toBeVisible();
  await expect(main.getByText(second)).toBeVisible();
  await expect(main.getByText(REPLY, { exact: true })).toBeVisible();
});

test("Send is disabled when empty; composer and picker lock while a reply streams, focus returns after", async ({
  page,
}) => {
  await page.goto("/chat");
  await expect(sendButton(page)).toBeDisabled();
  await composer(page).fill("   ");
  await expect(sendButton(page)).toBeDisabled();

  await send(page, SLOW_TEXT);
  const main = page.getByRole("main");
  await expect(main.getByText("Slowly streaming reply, part 1.")).toBeVisible();
  await expect(composer(page)).toBeDisabled();
  await expect(page.getByRole("combobox")).toBeDisabled();
  await expect(sendButton(page)).toBeDisabled();

  await expect(
    main.getByText("Slowly streaming reply, part 10."),
  ).toBeVisible();
  await expect(composer(page)).toBeEnabled();
  await expect(composer(page)).toBeFocused();
});

test("the picked model travels with the first turn and the next one", async ({
  page,
}) => {
  await page.goto("/chat");
  const picker = page.getByRole("combobox");
  await expect(picker.locator("option")).toHaveText([
    "Default",
    "Haiku",
    "Sonnet",
    "Opus",
  ]);
  await picker.selectOption(PICKED_MODEL);

  let request = page.waitForRequest(isChat);
  await startConversation(page, "Basics journey: the first turn's model");
  expect((await request).postDataJSON().model).toBe(PICKED_MODEL);
  await expect(page.getByRole("combobox")).toHaveValue(PICKED_MODEL);

  request = page.waitForRequest(isChat);
  await send(page, "Basics journey: the second turn's model");
  expect((await request).postDataJSON().model).toBe(PICKED_MODEL);
  const main = page.getByRole("main");
  await expect(main.getByText(REPLY, { exact: true })).toHaveCount(2);
});

test("deleting a conversation: Cancel keeps its row, confirming removes it", async ({
  page,
}) => {
  await page.goto("/chat");
  const path = await startConversation(page, "Basics journey: delete me");
  await openNewChat(page);

  let asked = "";
  page.once("dialog", (dialog) => {
    asked = dialog.message();
    void dialog.dismiss();
  });
  await deleteButton(page, path).click();
  await expect.poll(() => asked).toBe(CONFIRM);
  await expect(sidebarLink(page, path)).toBeVisible();

  page.once("dialog", (dialog) => void dialog.accept());
  await deleteButton(page, path).click();
  await expect(sidebarLink(page, path)).toHaveCount(0);
  await expect(page).toHaveURL(/\/chat$/);
});

test("deleting the open conversation lands on a fresh /chat", async ({
  page,
}) => {
  const text = "Basics journey: delete the open one";
  await page.goto("/chat");
  const path = await startConversation(page, text);

  page.once("dialog", (dialog) => void dialog.accept());
  await deleteButton(page, path).click();
  await expect(page).toHaveURL(/\/chat$/);
  await expect(sidebarLink(page, path)).toHaveCount(0);
  await expect(page.getByRole("main").getByText(text)).toHaveCount(0);
  await expect(composer(page)).toBeVisible();
});

// The list request is held open until the assertion has run, so "while
// loading" is a state the test controls, not a race it hopes to win.
test("the sidebar never says No conversations yet while its list is loading", async ({
  page,
}) => {
  let release = () => {};
  const held = new Promise<void>((resolve) => (release = resolve));
  await page.route("**/api/conversations", async (route) => {
    if (route.request().method() === "GET") await held;
    await route.fallback();
  });
  const listRequested = page.waitForRequest(
    (r) => r.method() === "GET" && r.url().endsWith("/api/conversations"),
  );

  await page.goto("/chat");
  await listRequested;
  await expect(composer(page)).toBeVisible();
  const nav = page.getByRole("navigation");
  await expect(nav.getByText(NO_CONVERSATIONS)).toHaveCount(0);

  release();
  await expect(
    nav.getByRole("link").first().or(nav.getByText(NO_CONVERSATIONS)),
  ).toBeVisible();
});

// Last in the file: it empties the member's sidebar, rows other files left
// behind included.
test("with every conversation deleted the sidebar says No conversations yet", async ({
  page,
}) => {
  await page.goto("/chat");
  const nav = page.getByRole("navigation");
  await expect(
    nav.getByRole("link").first().or(nav.getByText(NO_CONVERSATIONS)),
  ).toBeVisible();

  page.on("dialog", (dialog) => void dialog.accept());
  const deletes = nav.getByRole("button", { name: /^Delete / });
  for (let left = await deletes.count(); left > 0; left--) {
    await deletes.first().click();
    await expect(deletes).toHaveCount(left - 1);
  }
  await expect(nav.getByText(NO_CONVERSATIONS)).toBeVisible();
});
