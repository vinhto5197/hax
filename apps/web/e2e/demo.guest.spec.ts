import { expect, test } from "@playwright/test";
import { composer, INTERRUPTED, REPLY, send } from "./chat";

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

// DEMO_TURN_LIMIT is 3 (playwright.config.ts). A "flaky:" prompt fails on its
// first streaming request and answers "Recovered reply." after; "long:"
// streams twenty "Long reply, part N. " deltas 500 ms apart
// (fake-model/server.mjs).
const RECOVERED = "Recovered reply.";

test("A visitor's Try again counts as a turn", async ({ page }) => {
  const main = page.getByRole("main");
  const modal = page.getByRole("dialog", { name: "End of the demo" });
  const tryAgain = main.getByRole("button", { name: "Try again" });

  await page.goto("/");
  await send(page, "flaky: demo journey, a visitor's failed turn");
  await expect(main.getByRole("alert")).toContainText(INTERRUPTED);
  await expect(tryAgain).toBeVisible();
  await tryAgain.click();
  await expect(main.getByText(RECOVERED, { exact: true })).toHaveCount(1);

  await send(page, "Demo journey: the turn the retry left");
  await expect(main.getByText(REPLY, { exact: true })).toHaveCount(1);
  await expect(modal).toHaveCount(0);

  const refused = "Demo journey: one turn past the cap";
  await send(page, refused);
  await expect(modal).toBeVisible();
  await expect(main.getByText(refused)).toHaveCount(0);
  await expect(composer(page)).toBeDisabled();
});

test("A refused Try again after a Stop keeps the stopped reply shown", async ({
  page,
}) => {
  test.setTimeout(60_000);
  const main = page.getByRole("main");
  const modal = page.getByRole("dialog", { name: "End of the demo" });
  const longReply = main.getByText(/Long reply, part 1\./);

  await page.goto("/");
  for (let turn = 1; turn <= 2; turn++) {
    await send(page, `Demo journey: refused Try again, turn ${turn}`);
    await expect(main.getByText(REPLY, { exact: true })).toHaveCount(turn);
  }
  await send(page, "long: demo journey, the third turn stopped");
  await expect(main.getByText("Long reply, part 2.")).toBeVisible();
  await page.getByRole("button", { name: "Stop" }).click();
  await expect(main.getByText("You stopped this reply.")).toBeVisible();
  const partial = ((await longReply.textContent()) ?? "").trim();
  expect(partial).toContain("Long reply, part 2.");

  await main.getByRole("button", { name: "Try again" }).click();
  await expect(modal).toBeVisible();
  await expect(longReply).toHaveText(partial);
  await expect(main.getByText(/Long reply, part 20\./)).toHaveCount(0);
});
