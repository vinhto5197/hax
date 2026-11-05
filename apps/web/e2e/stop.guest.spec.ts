import { expect, test } from "@playwright/test";
import { composer, INTERRUPTED, send, stopButton } from "./chat";

// The guest prompt reaches the fake model like a member's: a "long:" message
// streams twenty "Long reply, part N. " deltas 500 ms apart
// (fake-model/server.mjs), about ten seconds.
const REPLY_RUNS_MS = 11_000;

test("A visitor can stop a demo reply: what was written stays and the composer is free", async ({
  page,
}) => {
  test.setTimeout(60_000);
  const text = "long: stop journey, a visitor's demo reply";
  const main = page.getByRole("main");
  const reply = main.getByText(/Long reply, part 1\./);

  await page.goto("/");
  await send(page, text);
  await expect(main.getByText("Long reply, part 2.")).toBeVisible();
  await expect(stopButton(page)).toBeEnabled();
  await stopButton(page).click();

  await expect(composer(page)).toBeEnabled();
  await expect(stopButton(page)).toHaveCount(0);
  const partial = ((await reply.textContent()) ?? "").trim();
  expect(partial).toContain("Long reply, part 2.");

  await page.waitForTimeout(REPLY_RUNS_MS);
  await expect(main.getByText(/Long reply, part 20\./)).toHaveCount(0);
  await expect(reply).toHaveText(partial);
  await expect(main.getByRole("alert")).toHaveCount(0);
  await expect(page.getByText(INTERRUPTED)).toHaveCount(0);
});
