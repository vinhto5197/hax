import { expect, test, type Page } from "@playwright/test";
import { fillSignup, uniqueEmail } from "./signup";

// Every signup here spends the shared per-IP signup budget (10 an hour in
// apps/api/routers/auth.py): one per test that needs an unverified account.
const PASSWORD = "login-journey-password";
const UNVERIFIED = "Verify your email first — check your inbox for the link.";
const GOOGLE_HINT = /^Signed up with Google\?/;
const VERIFIED_BANNER = "Email verified — log in to continue.";
const RESET_BANNER = "Password updated — log in to continue.";

async function signUp(page: Page, email: string) {
  await fillSignup(page, email, PASSWORD, "Login Journey");
  const inbox = page.getByRole("heading", { name: "Check your inbox" });
  await expect(inbox).toBeVisible();
}

async function logIn(page: Page, email: string, password: string) {
  await page.goto("/login");
  await page.getByPlaceholder("Email").fill(email);
  await page.getByPlaceholder("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Log in", exact: true }).click();
}

function resendButton(page: Page) {
  return page.getByRole("button", { name: "Resend verification email" });
}

test("wrong credentials show the generic message and the Google hint", async ({
  page,
}) => {
  await logIn(page, uniqueEmail("login", "51"), "not-the-password");

  await expect(page.getByText("Invalid email or password.")).toBeVisible();
  await expect(page.getByText(GOOGLE_HINT)).toBeVisible();
  await expect(resendButton(page)).toHaveCount(0);
  await expect(page).toHaveURL(/\/login$/);
});

test("a login the API never answers shows 'That took too long' and the button comes back", async ({
  page,
}) => {
  // The ten-second limit itself is Next's server-side call to the API
  // (lib/internalApi.test.ts); a browser cannot slow that call, so this
  // answers the sign-in request the way Auth.js does once authorize() has
  // failed with code "timeout".
  await page.route("**/auth/callback/credentials*", (route) =>
    route.fulfill({
      json: {
        url: new URL("/login?error=CredentialsSignin&code=timeout", page.url())
          .href,
      },
    }),
  );
  await logIn(page, uniqueEmail("login", "timeout"), PASSWORD);

  await expect(
    page.getByText("That took too long, please try again."),
  ).toBeVisible();
  await expect(page.getByText("Invalid email or password.")).toHaveCount(0);
  await expect(page.getByText(GOOGLE_HINT)).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Log in", exact: true }),
  ).toBeEnabled();
  await expect(page).toHaveURL(/\/login$/);
});

test("an unverified account sees the verify message and Resend, not the Google hint", async ({
  page,
}) => {
  const email = uniqueEmail("login", "52");
  await signUp(page, email);
  await logIn(page, email, PASSWORD);

  await expect(page.getByText(UNVERIFIED)).toBeVisible();
  await expect(resendButton(page)).toBeVisible();
  await expect(page.getByText(GOOGLE_HINT)).toHaveCount(0);
  await expect(page).toHaveURL(/\/login$/);
});

test("Resend on the unverified message shows the sent status", async ({
  page,
}) => {
  const email = uniqueEmail("login", "61");
  await signUp(page, email);
  await logIn(page, email, PASSWORD);
  await expect(page.getByText(UNVERIFIED)).toBeVisible();

  await resendButton(page).click();
  await expect(page.getByText("Sent.", { exact: true })).toBeVisible();
});

// The three branches of oauthErrorMessage in app/login/page.tsx.
const ERROR_MESSAGES = [
  {
    code: "google_unverified",
    message:
      "Google hasn't verified that email address, so it can't be used to sign in.",
  },
  {
    code: "OAuthCallbackError",
    message: "Google sign-in didn't complete. Please try again.",
  },
  {
    code: "Configuration",
    message: "Sign-in is temporarily unavailable. Please try again later.",
  },
];

test("each ?error= code the login page handles shows its own message", async ({
  page,
}) => {
  for (const { code, message } of ERROR_MESSAGES) {
    await page.goto(`/login?error=${code}`);
    await expect(page.getByText(message)).toBeVisible();
    for (const other of ERROR_MESSAGES) {
      if (other.code === code) continue;
      await expect(page.getByText(other.message)).toHaveCount(0);
    }
  }
});

// Google's own redirect when the consent screen is cancelled: no code, no iss.
test("a guest who cancels Google's consent screen lands on /login with the Google-retry message, not the unavailable one", async ({
  page,
}) => {
  const retry = ERROR_MESSAGES.find((e) => e.code === "OAuthCallbackError")!;
  const unavailable = ERROR_MESSAGES.find((e) => e.code === "Configuration")!;

  await page.goto("/auth/callback/google?error=access_denied&state=x");

  await expect(page).toHaveURL(/\/login\?(.*&)?error=OAuthCallbackError(&|$)/);
  await expect(page.getByText(retry.message)).toBeVisible();
  await expect(page.getByText(unavailable.message)).toHaveCount(0);
});

test("the ?verified=1 and ?reset=1 banners show, with the email prefilled", async ({
  page,
}) => {
  const email = page.getByPlaceholder("Email");

  await page.goto("/login?verified=1&email=verified%40example.com");
  await expect(page.getByText(VERIFIED_BANNER)).toBeVisible();
  await expect(email).toHaveValue("verified@example.com");

  await page.goto("/login?reset=1&email=reset%40example.com");
  await expect(page.getByText(RESET_BANNER)).toBeVisible();
  await expect(page.getByText(VERIFIED_BANNER)).toHaveCount(0);
  await expect(email).toHaveValue("reset@example.com");

  await page.goto("/login");
  const logInButton = page.getByRole("button", { name: "Log in", exact: true });
  await expect(logInButton).toBeVisible();
  await expect(email).toHaveValue("");
  await expect(page.getByText(VERIFIED_BANNER)).toHaveCount(0);
  await expect(page.getByText(RESET_BANNER)).toHaveCount(0);
});

test("Show and Hide toggle the password input between hidden and plain text", async ({
  page,
}) => {
  await page.goto("/login");
  const password = page.getByPlaceholder("Password", { exact: true });
  await password.fill("visible-secret");
  await expect(password).toHaveAttribute("type", "password");

  await page.getByRole("button", { name: "Show password" }).click();
  await expect(password).toHaveAttribute("type", "text");
  const hide = page.getByRole("button", { name: "Hide password" });
  await expect(hide).toHaveAttribute("aria-pressed", "true");

  await hide.click();
  await expect(password).toHaveAttribute("type", "password");
  await expect(password).toHaveValue("visible-secret");
});
