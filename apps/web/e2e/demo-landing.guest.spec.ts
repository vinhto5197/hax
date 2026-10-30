import { expect, test, type Page } from "@playwright/test";
import { composer, REPLY, send } from "./chat";

// Mirrors DEMO_CHIPS in app/page.tsx.
const CHIPS = [
  "What database does Hax use?",
  "Can another user see my files?",
  "How are my documents searched?",
];
const BLURB =
  "Hax is a chat that answers from your own documents. Try it without an account: ask about Hax itself.";
const NOTICE = "Hax is evolving. More specific capabilities coming soon.";

async function expectReplies(page: Page, count: number) {
  const main = page.getByRole("main");
  await expect(main.getByText(REPLY, { exact: true })).toHaveCount(count);
}

test("the landing page shows the notice, the blurb, three chips and the sign-in links, and no greeting", async ({
  page,
}) => {
  await page.goto("/");

  await expect(page.getByText(BLURB, { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { level: 1 })).toHaveCount(0);
  for (const chip of CHIPS) {
    await expect(page.getByRole("button", { name: chip })).toBeVisible();
  }
  const logIn = page.getByRole("link", { name: "Log in", exact: true });
  await expect(logIn).toHaveAttribute("href", "/login");
  const signUp = page.getByRole("link", { name: "Sign up", exact: true });
  await expect(signUp).toHaveAttribute("href", "/signup");
  const privacy = page.getByRole("link", { name: "Privacy", exact: true });
  await expect(privacy).toHaveAttribute("href", "/privacy");
});

test("a visitor's empty composer asks what Hax is", async ({ page }) => {
  await page.goto("/");
  await expect(composer(page)).toHaveAttribute(
    "placeholder",
    "Ask what Hax is…",
  );
});

test("the evolving notice sits right below the top bar on the landing, and above the guest line once the demo starts", async ({
  page,
}) => {
  await page.goto("/");
  const notice = page.getByText(NOTICE, { exact: true });
  await expect(notice).toBeVisible();
  const header = await page.locator("header").first().boundingBox();
  const noticeBox = await notice.boundingBox();
  expect(noticeBox!.y).toBeGreaterThanOrEqual(header!.y + header!.height);
  const blurbBox = await page.getByText(BLURB, { exact: true }).boundingBox();
  expect(noticeBox!.y).toBeLessThan(blurbBox!.y);

  await send(page, "Demo landing journey: the evolving notice");
  await expectReplies(page, 1);
  await expect(notice).toBeVisible();
  const guestLine = page.getByText(/^You're trying Hax as a guest/);
  expect((await notice.boundingBox())!.y).toBeLessThan(
    (await guestLine.boundingBox())!.y,
  );
});

test("a demo turn runs in place: the URL stays /", async ({ page }) => {
  await page.goto("/");
  await send(page, "Demo landing journey: does the URL move?");

  await expectReplies(page, 1);
  expect(new URL(page.url()).pathname).toBe("/");
  await page.goto("/");
  await expect(page.getByText(BLURB, { exact: true })).toBeVisible();
});

test("clicking a chip sends its text as the user turn and the reply follows", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: CHIPS[0] }).click();

  const main = page.getByRole("main");
  const question = main.getByText(CHIPS[0], { exact: true });
  await expect(question).toBeVisible();
  await expectReplies(page, 1);
  await expect(page.getByRole("button", { name: CHIPS[1] })).toHaveCount(0);

  const questionBox = await question.boundingBox();
  const replyBox = await main.getByText(REPLY, { exact: true }).boundingBox();
  expect(questionBox!.y).toBeLessThan(replyBox!.y);
});

test("the guest chat shows the banner with its links and no model picker", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.getByRole("combobox")).toHaveCount(0);
  await send(page, "Demo landing journey: the guest banner");
  await expectReplies(page, 1);

  const banner = page.getByText(/^You're trying Hax as a guest/);
  await expect(banner).toBeVisible();
  const signUp = banner.getByRole("link", { name: "sign up", exact: true });
  await expect(signUp).toHaveAttribute("href", "/signup");
  const logIn = banner.getByRole("link", { name: "Log in", exact: true });
  await expect(logIn).toHaveAttribute("href", "/login");
  await expect(page.getByRole("combobox")).toHaveCount(0);
  await expect(page.getByLabel("Model")).toHaveCount(0);
});

test("after three turns the fourth is refused: the End of the demo modal, no turn, composer disabled", async ({
  page,
}) => {
  const refused = "Demo landing journey: turn 4";
  await page.goto("/");
  for (let turn = 1; turn <= 3; turn++) {
    await send(page, `Demo landing journey: turn ${turn}`);
    await expectReplies(page, turn);
  }
  const modal = page.getByRole("dialog", { name: "End of the demo" });
  await expect(modal).toHaveCount(0);

  await send(page, refused);
  await expect(modal).toBeVisible();
  const signUp = modal.getByRole("link", { name: "Sign up", exact: true });
  await expect(signUp).toHaveAttribute("href", "/signup");
  await expect(page.getByRole("main").getByText(refused)).toHaveCount(0);
  await expect(composer(page)).toBeDisabled();
  await expectReplies(page, 3);
});
