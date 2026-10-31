import { expect, test, type Page, type Route } from "@playwright/test";
import { composer, REPLY, send } from "./chat";

const RATE_LIMITED =
  "Too many demo sessions from your network today. Log in, or try again tomorrow.";
const START_FAILED = "Couldn't start the demo. Please try again.";

async function stageDemoStart(
  page: Page,
  handle: (route: Route) => Promise<void>,
) {
  await page.route("**/auth/callback/anonymous**", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    await handle(route);
  });
}

async function expectComposerUsableAndNoReply(page: Page) {
  await expect(composer(page)).toBeEnabled();
  await expect(composer(page)).toBeEditable();
  await composer(page).fill("Trying again");
  await expect(composer(page)).toHaveValue("Trying again");
  await expect(
    page.getByRole("main").getByText(REPLY, { exact: true }),
  ).toHaveCount(0);
  expect(new URL(page.url()).pathname).toBe("/");
}

test("a rate-limited demo start shows the too-many-sessions message and leaves the composer usable", async ({
  page,
}) => {
  await stageDemoStart(page, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        url: new URL(
          "/auth/signin?error=CredentialsSignin&code=rate_limited",
          page.url(),
        ).href,
      }),
    }),
  );
  await page.goto("/");
  await send(page, "Demo start journey: rate limited");

  await expect(page.getByText(RATE_LIMITED, { exact: true })).toBeVisible();
  await expectComposerUsableAndNoReply(page);
});

test("a demo start that fails on the network shows the try-again message and leaves the composer usable", async ({
  page,
}) => {
  await stageDemoStart(page, (route) => route.abort());
  await page.goto("/");
  await send(page, "Demo start journey: network failure");

  await expect(page.getByText(START_FAILED, { exact: true })).toBeVisible();
  await expectComposerUsableAndNoReply(page);
});
