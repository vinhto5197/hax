import { expect, test } from "@playwright/test";
import {
  openNewChat,
  send,
  sidebarLink,
  SLOW_REPLY,
  startConversation,
} from "./chat";

const SLOW_TEXT = "slow: switch journey, the streaming conversation";
const NEXT_TEXT = "Switch journey: the conversation started mid-stream";
// Must exceed the fake model's slow reply (10 pieces x 300 ms in
// fake-model/server.mjs), so a stray late piece would land inside the window.
const QUIET_MS = 4_500;

test("New chat during a live reply keeps that reply and its conversation off the new chat", async ({
  page,
}) => {
  const main = page.getByRole("main");
  const nav = page.getByRole("navigation");
  const sidebarHrefs = () =>
    nav
      .getByRole("link")
      .evaluateAll((links) => links.map((l) => l.getAttribute("href")));

  await page.goto("/chat");
  await expect(
    nav.getByRole("link").first().or(nav.getByText("No conversations yet")),
  ).toBeVisible();
  const before = new Set(await sidebarHrefs());

  await send(page, SLOW_TEXT);
  await expect(main.getByText("Slowly streaming reply, part 1.")).toBeVisible();
  await expect(main.getByText("Slowly streaming reply, part 10.")).toHaveCount(
    0,
  );

  await openNewChat(page);
  const next = await startConversation(page, NEXT_TEXT);
  before.add(next);

  // The behaviour under test is an absence over time.
  const deadline = Date.now() + QUIET_MS;
  while (Date.now() < deadline) {
    expect(await page.getByText(SLOW_REPLY).count()).toBe(0);
    expect(await main.getByText(SLOW_TEXT).count()).toBe(0);
    expect(new URL(page.url()).pathname).toBe(next);
    await page.waitForTimeout(100);
  }
  await expect(main.getByText(NEXT_TEXT, { exact: true })).toBeVisible();

  let slow = "";
  await expect
    .poll(async () => {
      const added = (await sidebarHrefs()).filter(
        (href) => href && !before.has(href),
      );
      slow = added[0] ?? "";
      return added.length;
    })
    .toBe(1);

  await sidebarLink(page, slow).click();
  await expect(page).toHaveURL(new RegExp(`${slow}$`));
  await expect(main.getByText(SLOW_TEXT, { exact: true })).toBeVisible();
  await expect(main.getByText(NEXT_TEXT)).toHaveCount(0);
});
