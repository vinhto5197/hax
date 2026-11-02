import { expect, test, type Page, type TestInfo } from "@playwright/test";
import { composer, REPLY, send, startConversation } from "./chat";
import { cutStream, installStreamCut } from "./network";

// Scripted replies (fake-model/server.mjs): a "flaky:" prompt fails mid-reply
// on its first streaming request and answers "Recovered reply." on every
// later one for the same text (per run, so each journey uses its own text);
// "fail:" fails every time; "long:" streams twenty "Long reply, part N. "
// deltas 500 ms apart; "search:" runs a tool call whose follow-up waits
// 1.5 s before any text, the window a Stop lands in before the first word.
const INTERRUPTED = "The reply was interrupted.";
const STOPPED = "You stopped this reply.";
const RECOVERED = "Recovered reply.";
const SEARCH_ANSWER = "Here is what your documents say.";
const BUSY = "A reply is already in progress in this conversation.";
const LONG_REPLY = Array.from(
  { length: 20 },
  (_, i) => `Long reply, part ${i + 1}. `,
)
  .join("")
  .trim();
const REPLY_LANDS_MS = 25_000;
const DESKTOP = { width: 1280, height: 800 };
const PHONE = { width: 390, height: 844 };

// Scoped to the chat: Next.js renders an empty role="alert" route announcer
// outside it on every page.
function errorLine(page: Page) {
  return page.getByRole("main").getByRole("alert");
}

function tryAgain(page: Page) {
  return page.getByRole("main").getByRole("button", { name: "Try again" });
}

function stopButton(page: Page) {
  return page.getByRole("button", { name: "Stop" });
}

function stoppedLine(page: Page) {
  return page.getByRole("main").getByText(STOPPED);
}

function longReplies(page: Page) {
  return page.getByRole("main").getByText(/Long reply, part 1\./);
}

async function expectInterrupted(page: Page) {
  await expect(errorLine(page)).toBeVisible();
  await expect(errorLine(page)).toContainText(INTERRUPTED);
  await expect(tryAgain(page)).toBeVisible();
}

async function shoot(page: Page, testInfo: TestInfo, name: string) {
  const path = testInfo.outputPath(`${name}.png`);
  await page.screenshot({ path, fullPage: true });
  await testInfo.attach(name, { path, contentType: "image/png" });
}

test("A failed reply offers Try again, and Try again writes the reply under the same question without sending it twice", async ({
  page,
}, testInfo) => {
  test.setTimeout(60_000);
  const text = "flaky: try again journey, a failed reply recovered";
  const main = page.getByRole("main");
  await page.setViewportSize(DESKTOP);

  await page.goto("/chat");
  await send(page, text);
  await expectInterrupted(page);
  await expect(page).toHaveURL(/\/chat\/[^/]+$/);

  for (const scheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    await page.setViewportSize(DESKTOP);
    await expect(tryAgain(page)).toBeVisible();
    await shoot(page, testInfo, `try-again-desktop-${scheme}`);
    await page.setViewportSize(PHONE);
    await expect(tryAgain(page)).toBeVisible();
    await shoot(page, testInfo, `try-again-phone-${scheme}`);
  }
  await page.emulateMedia({ colorScheme: "light" });
  await page.setViewportSize(DESKTOP);

  await tryAgain(page).click();
  await expect(main.getByText(RECOVERED, { exact: true })).toBeVisible();
  await expect(main.getByText(RECOVERED, { exact: true })).toHaveCount(1);
  await expect(main.getByText(text, { exact: true })).toHaveCount(1);
  await expect(errorLine(page)).toHaveCount(0);
  await expect(tryAgain(page)).toHaveCount(0);
  await expect(composer(page)).toBeEnabled();

  await page.reload();
  await expect(main.getByText(RECOVERED, { exact: true })).toHaveCount(1);
  await expect(main.getByText(text, { exact: true })).toHaveCount(1);
  await expect(errorLine(page)).toHaveCount(0);
  await expect(tryAgain(page)).toHaveCount(0);
});

test("Try again after a reload of an interrupted conversation writes the reply", async ({
  page,
}) => {
  const text = "flaky: try again journey, recovered after a reload";
  const main = page.getByRole("main");

  await page.goto("/chat");
  await send(page, text);
  await expectInterrupted(page);
  await expect(page).toHaveURL(/\/chat\/[^/]+$/);

  await page.reload();
  await expect(main.getByText(text, { exact: true })).toBeVisible();
  await expectInterrupted(page);

  await tryAgain(page).click();
  await expect(main.getByText(RECOVERED, { exact: true })).toBeVisible();
  await expect(main.getByText(RECOVERED, { exact: true })).toHaveCount(1);
  await expect(main.getByText(text, { exact: true })).toHaveCount(1);
  await expect(errorLine(page)).toHaveCount(0);

  await page.reload();
  await expect(main.getByText(RECOVERED, { exact: true })).toHaveCount(1);
  await expect(main.getByText(text, { exact: true })).toHaveCount(1);
});

test("Try again is not offered on other errors: a reply already in progress has no Try again", async ({
  context,
}) => {
  const pageA = await context.newPage();
  const pageB = await context.newPage();
  const mainB = pageB.getByRole("main");

  await pageA.goto("/chat");
  const path = await startConversation(
    pageA,
    "Try again journey: the first message before the busy refusal",
  );

  // B is loaded before A's slow turn starts, so B's send lands while A's
  // reply holds the turn.
  await pageB.goto(path);
  await expect(mainB.getByText(REPLY, { exact: true })).toHaveCount(1);

  await send(pageA, "slow: try again journey, the reply in flight");
  await expect(
    pageA.getByRole("main").getByText("Slowly streaming reply, part 1."),
  ).toBeVisible();

  await send(pageB, "Try again journey: sent while the other tab streams");
  await expect(pageB.getByText(BUSY)).toBeVisible();
  await expect(tryAgain(pageB)).toHaveCount(0);
});

test("Try again after a Stop replaces the stopped reply", async ({ page }) => {
  test.setTimeout(90_000);
  const text = "long: try again journey, stopped then regenerated";
  const main = page.getByRole("main");

  await page.goto("/chat");
  await send(page, text);
  await expect(main.getByText("Long reply, part 2.")).toBeVisible();
  await stopButton(page).click();

  await expect(stoppedLine(page)).toBeVisible();
  await expect(tryAgain(page)).toBeVisible();
  await expect(errorLine(page)).toHaveCount(0);
  await expect(longReplies(page)).toHaveCount(1);
  const partial = ((await longReplies(page).textContent()) ?? "").trim();
  expect(partial).not.toContain("Long reply, part 20.");

  await tryAgain(page).click();
  await expect(stoppedLine(page)).toHaveCount(0);
  await expect(main.getByText(LONG_REPLY, { exact: true })).toBeVisible({
    timeout: REPLY_LANDS_MS,
  });
  await expect(longReplies(page)).toHaveCount(1);
  await expect(main.getByText(partial, { exact: true })).toHaveCount(0);
  await expect(main.getByText(text, { exact: true })).toHaveCount(1);
  await expect(errorLine(page)).toHaveCount(0);
  await expect(composer(page)).toBeEnabled();

  await page.reload();
  await expect(main.getByText(text, { exact: true })).toHaveCount(1);
  await expect(main.getByText(LONG_REPLY, { exact: true })).toHaveCount(1);
  await expect(longReplies(page)).toHaveCount(1);
  await expect(stoppedLine(page)).toHaveCount(0);
});

test("Try again after a Stop before any text writes the reply", async ({
  page,
}) => {
  test.setTimeout(60_000);
  const text = "search: try again journey, stopped before the first word";
  const main = page.getByRole("main");

  await page.goto("/chat");
  await send(page, text);
  // The search's follow-up waits 1.5 s before any text: Stop lands there.
  await expect(main.getByText("Searching documents…")).toBeVisible();
  await stopButton(page).click();

  await expect(stoppedLine(page)).toBeVisible();
  await expect(tryAgain(page)).toBeVisible();
  await expect(main.getByText(SEARCH_ANSWER, { exact: true })).toHaveCount(0);
  await expect(errorLine(page)).toHaveCount(0);

  await tryAgain(page).click();
  await expect(main.getByText(SEARCH_ANSWER, { exact: true })).toBeVisible();
  await expect(main.getByText(SEARCH_ANSWER, { exact: true })).toHaveCount(1);
  await expect(main.getByText(text, { exact: true })).toHaveCount(1);
  await expect(stoppedLine(page)).toHaveCount(0);
  await expect(errorLine(page)).toHaveCount(0);

  await page.reload();
  await expect(main.getByText(SEARCH_ANSWER, { exact: true })).toHaveCount(1);
  await expect(main.getByText(text, { exact: true })).toHaveCount(1);
});

test("A Try again after another page answered shows that answer, with no line", async ({
  context,
}) => {
  const text = "flaky: try again journey, answered by the other page";
  const pageA = await context.newPage();
  const pageB = await context.newPage();
  const mainA = pageA.getByRole("main");
  const mainB = pageB.getByRole("main");

  await pageA.goto("/chat");
  await send(pageA, text);
  await expectInterrupted(pageA);
  await expect(pageA).toHaveURL(/\/chat\/[^/]+$/);
  const path = new URL(pageA.url()).pathname;

  await pageB.goto(path);
  await expectInterrupted(pageB);
  await tryAgain(pageB).click();
  await expect(mainB.getByText(RECOVERED, { exact: true })).toHaveCount(1);

  // A still shows the interrupted line from before B answered.
  await expect(errorLine(pageA)).toContainText(INTERRUPTED);
  // A shows no reply, so it must not ask to replace one, and the server
  // refuses rather than delete B's: a delete-and-rewrite would also leave
  // one "Recovered reply.", so the text alone cannot tell.
  const retried = pageA.waitForResponse((r) =>
    /\/api\/conversations\/[^/]+\/retry$/.test(new URL(r.url()).pathname),
  );
  await tryAgain(pageA).click();
  const response = await retried;
  expect(response.request().postDataJSON()).toMatchObject({ replace: false });
  expect(response.status()).toBe(409);
  expect(await response.json()).toEqual({ detail: "already_answered" });
  await expect(mainA.getByText(RECOVERED, { exact: true })).toBeVisible();
  await expect(mainA.getByText(RECOVERED, { exact: true })).toHaveCount(1);
  await expect(mainA.getByText(text, { exact: true })).toHaveCount(1);
  await expect(errorLine(pageA)).toHaveCount(0);
  await expect(pageA.getByText(INTERRUPTED)).toHaveCount(0);
  await expect(tryAgain(pageA)).toHaveCount(0);

  // Nothing was deleted: B's reply is still the conversation's answer.
  await pageB.reload();
  await expect(mainB.getByText(RECOVERED, { exact: true })).toHaveCount(1);
  await expect(mainB.getByText(text, { exact: true })).toHaveCount(1);
  await expect(errorLine(pageB)).toHaveCount(0);
});

test("A stale tab's Try again never deletes a reply it did not show", async ({
  context,
}) => {
  test.setTimeout(60_000);
  const longText = "long: try again journey, the stale tab's stopped reply";
  const newer = "Try again journey: the other tab's newer question";
  const pageA = await context.newPage();
  const pageB = await context.newPage();
  const mainA = pageA.getByRole("main");
  const mainB = pageB.getByRole("main");

  await pageA.goto("/chat");
  const path = await startConversation(
    pageA,
    "Try again journey: the stale tab's first message",
  );
  await send(pageA, longText);
  await expect(mainA.getByText("Long reply, part 2.")).toBeVisible();
  await stopButton(pageA).click();
  await expect(stoppedLine(pageA)).toBeVisible();
  await expect(tryAgain(pageA)).toBeVisible();
  const partial = ((await longReplies(pageA).textContent()) ?? "").trim();

  await pageB.goto(path);
  await expect(longReplies(pageB)).toHaveCount(1);
  await send(pageB, newer);
  await expect(mainB.getByText(REPLY, { exact: true })).toHaveCount(2);

  await tryAgain(pageA).click();
  await expect(mainA.getByText(newer, { exact: true })).toBeVisible();
  await expect(mainA.getByText(REPLY, { exact: true })).toHaveCount(2);
  await expect(longReplies(pageA)).toHaveCount(1);
  await expect(longReplies(pageA)).toHaveText(partial);
  await expect(mainA.getByText(longText, { exact: true })).toHaveCount(1);
  await expect(stoppedLine(pageA)).toHaveCount(0);
  await expect(errorLine(pageA)).toHaveCount(0);
  await expect(tryAgain(pageA)).toHaveCount(0);

  await pageB.reload();
  await expect(longReplies(pageB)).toHaveText(partial);
  await expect(mainB.getByText(newer, { exact: true })).toHaveCount(1);
  await expect(mainB.getByText(REPLY, { exact: true })).toHaveCount(2);
});

test("Try again after a Stop whose stream was lost replaces the stopped reply", async ({
  page,
}) => {
  test.setTimeout(90_000);
  const text = "long: try again journey, stopped and the stream lost";
  const main = page.getByRole("main");
  await installStreamCut(page);
  // The stream is cut as the stop request leaves, so the page never reads
  // the stopped reply's [DONE]: the poll brings the kept partial instead.
  await page.route("**/api/conversations/*/stop", async (route) => {
    await cutStream(page);
    await route.fulfill({ response: await route.fetch() });
  });

  await page.goto("/chat");
  await send(page, text);
  await expect(main.getByText("Long reply, part 2.")).toBeVisible();
  await stopButton(page).click();

  await expect(stoppedLine(page)).toBeVisible({ timeout: 15_000 });
  await expect(tryAgain(page)).toBeVisible();
  await expect(longReplies(page)).toHaveCount(1);
  const partial = ((await longReplies(page).textContent()) ?? "").trim();
  expect(partial).toContain("Long reply, part 2.");
  expect(partial).not.toContain("Long reply, part 20.");

  await tryAgain(page).click();
  await expect(stoppedLine(page)).toHaveCount(0);
  await expect(main.getByText(LONG_REPLY, { exact: true })).toBeVisible({
    timeout: REPLY_LANDS_MS,
  });
  await expect(longReplies(page)).toHaveCount(1);
  await expect(main.getByText(text, { exact: true })).toHaveCount(1);
  await expect(errorLine(page)).toHaveCount(0);

  await page.reload();
  await expect(main.getByText(LONG_REPLY, { exact: true })).toHaveCount(1);
  await expect(longReplies(page)).toHaveCount(1);
});

test("Try again that fails again shows the interrupted line with Try again", async ({
  page,
}) => {
  const text = "fail: try again journey, the model fails every time";
  const main = page.getByRole("main");

  await page.goto("/chat");
  await send(page, text);
  await expectInterrupted(page);

  await tryAgain(page).click();
  // The retry streams before it fails: proof a second attempt ran.
  await expect(main.getByText("Failing reply, part 1.")).toBeVisible();
  await expectInterrupted(page);
  await expect(main.getByText(/Failing reply/)).toHaveCount(0);
  await expect(main.getByText(text, { exact: true })).toHaveCount(1);
  await expect(composer(page)).toBeEnabled();
});
