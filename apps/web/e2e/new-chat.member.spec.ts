import { expect, test } from "@playwright/test";
import {
  composer,
  openNewChat,
  REPLY,
  sidebarLink,
  startConversation,
} from "./chat";

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

test("a member's empty composer says What's up?", async ({ page }) => {
  await page.goto("/chat");
  await expect(composer(page)).toHaveAttribute("placeholder", "What's up?");
});

// The worker titles a conversation through the fake model, which answers a
// title only for a first message starting with `title:`, after 2 s.
test("row 7: a new conversation's sidebar row reads Untitled, then Fake model title without a reload", async ({
  page,
}) => {
  await page.goto("/chat");
  const path = await startConversation(
    page,
    "title: plan a picnic by the river",
  );
  const row = sidebarLink(page, path);
  await expect(row).toContainText("Untitled");

  // A marker on the window survives only if the page is never reloaded.
  await page.evaluate(() => {
    (window as unknown as { titleMarker: string }).titleMarker = "kept";
  });

  await expect(row).toContainText("Fake model title", { timeout: 20_000 });
  await expect(row).not.toContainText("Untitled");
  expect(
    await page.evaluate(
      () => (window as unknown as { titleMarker?: string }).titleMarker,
    ),
  ).toBe("kept");
  await expect(page).toHaveURL(new RegExp(`${path}$`));
});
