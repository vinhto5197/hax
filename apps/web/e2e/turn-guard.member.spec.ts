import { expect, test } from "@playwright/test";
import { REPLY, send, startConversation } from "./chat";

const BUSY = "A reply is already in progress in this conversation.";
const SLOW_TEXT = "slow: turn guard journey, the reply in flight";
const REFUSED_TEXT = "Turn guard journey: sent while the other tab streams";
const RETRY_TEXT = "Turn guard journey: sent after the other tab finished";

test("A second tab cannot send while a reply streams in the same conversation, and can once it ends", async ({
  context,
}) => {
  const pageA = await context.newPage();
  const pageB = await context.newPage();
  const mainA = pageA.getByRole("main");
  const mainB = pageB.getByRole("main");

  await pageA.goto("/chat");
  const path = await startConversation(
    pageA,
    "Turn guard journey: the first message",
  );

  // B is loaded before A's slow turn starts, so B's send lands inside the
  // three-second window the fake model's slow reply keeps the turn open.
  await pageB.goto(path);
  await expect(mainB.getByText(REPLY, { exact: true })).toHaveCount(1);

  await send(pageA, SLOW_TEXT);
  await expect(
    mainA.getByText("Slowly streaming reply, part 1."),
  ).toBeVisible();
  await expect(mainA.getByText("Slowly streaming reply, part 10.")).toHaveCount(
    0,
  );

  await send(pageB, REFUSED_TEXT);
  await expect(pageB.getByText(BUSY)).toBeVisible();
  await expect(mainB.getByText(REFUSED_TEXT)).toHaveCount(0);
  await expect(mainA.getByText("Slowly streaming reply, part 10.")).toHaveCount(
    0,
  );

  await expect(
    mainA.getByText("Slowly streaming reply, part 10."),
  ).toBeVisible();

  await send(pageB, RETRY_TEXT);
  await expect(mainB.getByText(RETRY_TEXT, { exact: true })).toBeVisible();
  await expect(mainB.getByText(REPLY, { exact: true })).toHaveCount(2);
  await expect(pageB.getByText(BUSY)).toHaveCount(0);
  await expect(mainB.getByText(REFUSED_TEXT)).toHaveCount(0);
});
