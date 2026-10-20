import { expect, test, type Page } from "@playwright/test";
import { openNewChat, REPLY, sidebarLink, startConversation } from "./chat";

const A_TEXT = "History journey: conversation A";
const B_TEXT = "History journey: conversation B";

async function expectShowing(
  page: Page,
  path: string,
  shown: string,
  hidden: string,
) {
  const main = page.getByRole("main");
  await expect(page).toHaveURL(new RegExp(`${path}$`));
  await expect(main.getByText(shown, { exact: true })).toBeVisible();
  await expect(main.getByText(REPLY, { exact: true })).toBeVisible();
  await expect(main.getByText(hidden)).toHaveCount(0);
}

test("reload, back and forward each show the conversation in the address bar", async ({
  page,
}) => {
  await page.goto("/chat");
  const a = await startConversation(page, A_TEXT);
  await openNewChat(page);
  const b = await startConversation(page, B_TEXT);

  // Sidebar clicks push real history entries, after the entry B was created on.
  await sidebarLink(page, a).click();
  await expectShowing(page, a, A_TEXT, B_TEXT);
  await sidebarLink(page, b).click();
  await expectShowing(page, b, B_TEXT, A_TEXT);

  await page.reload();
  await expectShowing(page, b, B_TEXT, A_TEXT);

  await page.goBack();
  await expectShowing(page, a, A_TEXT, B_TEXT);

  await page.goForward();
  await expectShowing(page, b, B_TEXT, A_TEXT);

  // Two entries back from the clicked B is the entry B was created on, whose
  // URL was rewritten in place by the first reply.
  await page.goBack();
  await expectShowing(page, a, A_TEXT, B_TEXT);
  await page.goBack();
  await expectShowing(page, b, B_TEXT, A_TEXT);
});
