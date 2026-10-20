import { expect, test } from "@playwright/test";
import { REPLY, send } from "./chat";

test("a guest on the landing page sends a message and the reply appears below it", async ({
  page,
}) => {
  await page.goto("/");
  await send(page, "Hi, what is hax?");

  const main = page.getByRole("main");
  const question = main.getByText("Hi, what is hax?", { exact: true });
  const reply = main.getByText(REPLY, { exact: true });
  await expect(question).toBeVisible();
  await expect(reply).toBeVisible();

  const questionBox = await question.boundingBox();
  const replyBox = await reply.boundingBox();
  expect(questionBox!.y).toBeLessThan(replyBox!.y);
});
