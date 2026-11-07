import { expect, test } from "@playwright/test";
import { composer, send } from "./chat";

// Narration before a tool call is withdrawn: the fake model's `narrate:`
// prompt streams "Let me look that up." ahead of its search_documents call,
// and the reply the member keeps is the follow-up's answer alone.
const NARRATION = "Let me look that up.";
const ANSWER = "Here is what your documents say.";

test("narration streamed before a search is withdrawn: the finished reply, and the reply after a reload, read only the answer", async ({
  page,
}) => {
  const text = `narrate: where are the orchard notes ${Date.now()}`;
  await page.goto("/chat");
  await send(page, text);

  const main = page.getByRole("main");
  await expect(main.getByText(ANSWER, { exact: true })).toBeVisible();
  await expect(composer(page)).toBeEnabled();
  await expect(main.getByText(text, { exact: true })).toHaveCount(1);
  await expect(main.getByText(ANSWER, { exact: true })).toHaveCount(1);
  await expect(main).not.toContainText(NARRATION);
  await expect(page).toHaveURL(/\/chat\/[^/]+$/);

  await page.reload();
  await expect(main.getByText(text, { exact: true })).toHaveCount(1);
  await expect(main.getByText(ANSWER, { exact: true })).toHaveCount(1);
  await expect(main).not.toContainText(NARRATION);
});
