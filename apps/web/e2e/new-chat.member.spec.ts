import { expect, test } from "@playwright/test";
import { openNewChat, REPLY, sidebarLink, startConversation } from "./chat";

test("New chat clears the screen and the next message starts a separate conversation", async ({
  page,
}) => {
  await page.goto("/chat");
  const main = page.getByRole("main");

  const first = await startConversation(page, "First conversation opener");

  await openNewChat(page);
  await expect(main.getByText("First conversation opener")).toHaveCount(0);
  await expect(main.getByText(REPLY)).toHaveCount(0);

  const second = await startConversation(page, "Second conversation opener");
  expect(second).not.toBe(first);
  await expect(main.getByText("First conversation opener")).toHaveCount(0);

  await expect(sidebarLink(page, first)).toBeVisible();
});
