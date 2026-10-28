import { expect, test, type Page } from "@playwright/test";
import { composer, REPLY, send } from "./chat";

// Mirrors DEMO_CHIPS in app/page.tsx.
const CHIPS = [
  "What database does hax use?",
  "Can another user see my files?",
  "How are my documents searched?",
];
// Every line pickGreeting (lib/greeting.ts) can produce with no name.
const GREETING =
  /^(Good (morning|afternoon|evening)|Early bird gets the worm|Happy \w+|Pushing through the day\?|Winding down\?|How was your \w+\?|Staying up late\?|Burning the midnight oil\?|Still at it\?)$/;
const BLURB =
  "hax is a chat that answers from your own documents. Try it without an account: ask about hax itself.";

async function expectReplies(page: Page, count: number) {
  const main = page.getByRole("main");
  await expect(main.getByText(REPLY, { exact: true })).toHaveCount(count);
}

test("the landing page shows the greeting, the blurb, three chips and the sign-in links", async ({
  page,
}) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { level: 1 })).toHaveText(GREETING);
  await expect(page.getByText(BLURB)).toBeVisible();
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

test("a demo turn runs in place: the URL stays /", async ({ page }) => {
  await page.goto("/");
  await send(page, "Demo landing journey: does the URL move?");

  await expectReplies(page, 1);
  expect(new URL(page.url()).pathname).toBe("/");
  await page.goto("/");
  await expect(page.getByText(BLURB)).toBeVisible();
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

  const banner = page.getByText(/^You're trying hax as a guest/);
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
