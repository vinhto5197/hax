import { expect, test, type Page, type TestInfo } from "@playwright/test";

// The member's note about themselves: the account menu in the sidebar, the
// About you dialog, and the note's persistence. Every test clears the seeded
// member's note first, through the API's own origin (the e2e web on :3001 has
// no /api rewrite; the session cookie is sent across ports on localhost).
const PROFILE_URL = "http://localhost:8001/api/me/profile";
const WEB_ORIGIN = "http://localhost:3001";
const DESKTOP = { width: 1280, height: 800 };
const PHONE = { width: 390, height: 844 };
const HELP =
  "Tell hax about yourself: what you do, what you know, how you like answers. hax reads this in every conversation.";
const PRIVACY_NOTE_LINE = "Your note about yourself, if you write one.";

test.beforeEach(async ({ page }) => {
  const cleared = await page.request.put(PROFILE_URL, {
    data: { about: "" },
    headers: { Origin: WEB_ORIGIN },
  });
  expect(cleared.status()).toBe(200);
});

function accountButton(page: Page) {
  return page.getByRole("button", { name: "Account menu" });
}

function menuItem(page: Page, text: string) {
  return page.getByText(text, { exact: true });
}

function aboutYouDialog(page: Page) {
  return page.getByRole("dialog", { name: "About you" });
}

function noteField(page: Page) {
  return aboutYouDialog(page).getByRole("textbox", { name: "About you" });
}

function saveButton(page: Page) {
  return aboutYouDialog(page).getByRole("button", { name: "Save" });
}

function drawer(page: Page) {
  return page.getByRole("dialog", { name: "Menu" });
}

async function openAboutYou(page: Page) {
  await accountButton(page).click();
  await menuItem(page, "About you").click();
  await expect(aboutYouDialog(page)).toBeVisible();
  // The textarea is disabled until the saved note has loaded.
  await expect(noteField(page)).toBeEnabled();
}

async function openDrawer(page: Page) {
  await page.getByRole("button", { name: "Open menu" }).click();
  await expect(drawer(page)).toBeVisible();
}

async function shot(page: Page, testInfo: TestInfo, name: string) {
  const path = testInfo.outputPath(`${name}.png`);
  await page.screenshot({ path });
  await testInfo.attach(name, { path, contentType: "image/png" });
}

test.describe("desktop", () => {
  test.use({ viewport: DESKTOP });

  test("the account button opens a menu with About you, Privacy and Sign out, and Escape closes it", async ({
    page,
  }, testInfo) => {
    await page.goto("/chat");
    const sidebar = page.getByRole("complementary");
    await sidebar.getByRole("button", { name: "Account menu" }).click();

    const items = ["About you", "Privacy", "Sign out"].map((text) =>
      menuItem(page, text),
    );
    for (const item of items) await expect(item).toBeVisible();
    const tops = await Promise.all(
      items.map(async (item) => (await item.boundingBox())!.y),
    );
    expect(tops).toEqual([...tops].sort((a, b) => a - b));
    await shot(page, testInfo, "account-menu-desktop");

    await page.keyboard.press("Escape");
    for (const item of items) await expect(item).toBeHidden();
  });

  test("a click outside closes the account menu", async ({ page }) => {
    await page.goto("/chat");
    await accountButton(page).click();
    await expect(menuItem(page, "Privacy")).toBeVisible();

    await page.getByRole("main").click({ position: { x: 600, y: 300 } });
    await expect(menuItem(page, "Privacy")).toBeHidden();
  });

  test("About you opens the dialog with the help line and the counter; typing updates the counter and Save waits for a change", async ({
    page,
  }, testInfo) => {
    await page.goto("/chat");
    await openAboutYou(page);

    const dialog = aboutYouDialog(page);
    await expect(dialog).toHaveAttribute("aria-modal", "true");
    await expect(dialog.getByText(HELP, { exact: true })).toBeVisible();
    await expect(dialog.getByText("0 / 1000", { exact: true })).toBeVisible();
    await expect(noteField(page)).toHaveValue("");
    await expect(noteField(page)).toBeFocused();
    await expect(saveButton(page)).toBeDisabled();
    await expect(dialog.getByRole("button", { name: "Cancel" })).toBeVisible();

    await noteField(page).fill("I bake bread");
    await expect(dialog.getByText("12 / 1000", { exact: true })).toBeVisible();
    await expect(saveButton(page)).toBeEnabled();
    await shot(page, testInfo, "about-you-dialog-desktop");

    await noteField(page).fill("   ");
    await expect(dialog.getByText("0 / 1000", { exact: true })).toBeVisible();
    await expect(saveButton(page)).toBeDisabled();
  });

  test("saving closes the dialog, and after a reload the dialog shows the saved text", async ({
    page,
  }) => {
    const note = "I am a pastry chef; keep answers short.";
    await page.goto("/chat");
    await openAboutYou(page);
    await noteField(page).fill(note);
    await saveButton(page).click();
    await expect(aboutYouDialog(page)).toHaveCount(0);

    await page.reload();
    await openAboutYou(page);
    await expect(noteField(page)).toHaveValue(note);
    await expect(
      aboutYouDialog(page).getByText(`${note.length} / 1000`, { exact: true }),
    ).toBeVisible();
    await expect(saveButton(page)).toBeDisabled();
  });

  test("clearing the text and saving removes the note", async ({ page }) => {
    await page.goto("/chat");
    await openAboutYou(page);
    await noteField(page).fill("A note that will be removed.");
    await saveButton(page).click();
    await expect(aboutYouDialog(page)).toHaveCount(0);

    await openAboutYou(page);
    await expect(noteField(page)).toHaveValue("A note that will be removed.");
    await noteField(page).fill("");
    await expect(saveButton(page)).toBeEnabled();
    await saveButton(page).click();
    await expect(aboutYouDialog(page)).toHaveCount(0);

    await page.reload();
    await openAboutYou(page);
    await expect(noteField(page)).toHaveValue("");
  });

  test("Cancel closes the dialog without saving", async ({ page }) => {
    await page.goto("/chat");
    await openAboutYou(page);
    await noteField(page).fill("never saved");
    await aboutYouDialog(page).getByRole("button", { name: "Cancel" }).click();
    await expect(aboutYouDialog(page)).toHaveCount(0);

    await openAboutYou(page);
    await expect(noteField(page)).toHaveValue("");
  });

  test("1001 characters disables Save, and 1000 enables it", async ({
    page,
  }) => {
    await page.goto("/chat");
    await openAboutYou(page);

    await noteField(page).fill("x".repeat(1001));
    await expect(
      aboutYouDialog(page).getByText("1001 / 1000", { exact: true }),
    ).toBeVisible();
    await expect(saveButton(page)).toBeDisabled();

    await noteField(page).fill("x".repeat(1000) + " ");
    await expect(
      aboutYouDialog(page).getByText("1000 / 1000", { exact: true }),
    ).toBeVisible();
    await expect(saveButton(page)).toBeEnabled();
  });

  test("Privacy goes to /privacy, and the page names the note", async ({
    page,
  }) => {
    await page.goto("/chat");
    await accountButton(page).click();
    await menuItem(page, "Privacy").click();
    await expect(page).toHaveURL(/\/privacy$/);
    await expect(
      page.getByText(PRIVACY_NOTE_LINE, { exact: false }),
    ).toBeVisible();
    await expect(
      page.getByText(
        "Anthropic receives your messages, your note about yourself and relevant excerpts of your documents to generate replies.",
        { exact: false },
      ),
    ).toBeVisible();
  });

  // Signing out here would leave the seeded member signed out for the rest of
  // the file; routing.member.spec.ts's account block covers Sign out.
  test.skip("Sign out in the account menu signs the member out", async () => {});
});

test.describe("phone", () => {
  test.use({ viewport: PHONE });

  test("at 390x844 the menu opens inside the drawer, the dialog fits the width, and Escape closes only the menu or the dialog", async ({
    page,
  }, testInfo) => {
    await page.goto("/chat");
    await openDrawer(page);

    await drawer(page).getByRole("button", { name: "Account menu" }).click();
    const privacy = drawer(page).getByText("Privacy", { exact: true });
    await expect(privacy).toBeVisible();
    await expect(
      drawer(page).getByText("About you", { exact: true }),
    ).toBeVisible();
    await expect(
      drawer(page).getByText("Sign out", { exact: true }),
    ).toBeVisible();
    await shot(page, testInfo, "account-menu-phone");

    await page.keyboard.press("Escape");
    await expect(privacy).toBeHidden();
    await expect(drawer(page)).toBeVisible();

    await openAboutYou(page);
    await noteField(page).fill("Phone typing");
    // The full width less the page's side gutter on each side.
    const box = (await aboutYouDialog(page).boundingBox())!;
    expect(box.x).toBeGreaterThan(0);
    expect(box.x).toBeLessThanOrEqual(24);
    expect(box.x + box.width).toBeLessThan(PHONE.width);
    expect(box.width).toBeGreaterThanOrEqual(PHONE.width - 48);
    await shot(page, testInfo, "about-you-dialog-phone");

    await page.keyboard.press("Escape");
    await expect(aboutYouDialog(page)).toHaveCount(0);
    await expect(drawer(page)).toBeVisible();
  });

  test("saving at phone width keeps the drawer open", async ({ page }) => {
    await page.goto("/chat");
    await openDrawer(page);
    await openAboutYou(page);
    await noteField(page).fill("Saved from a phone");
    await saveButton(page).click();
    await expect(aboutYouDialog(page)).toHaveCount(0);
    await expect(drawer(page)).toBeVisible();
  });

  test("a tap beside the dialog on a phone neither closes it nor the drawer, and Escape after it closes only the dialog", async ({
    page,
  }) => {
    await page.goto("/chat");
    await openDrawer(page);
    await openAboutYou(page);
    await noteField(page).fill("Do not lose me");

    // Near the bottom-right corner: outside a centred dialog, over the right
    // edge where the drawer's own close scrim sits.
    await page.mouse.click(PHONE.width - 4, PHONE.height - 4);
    await expect(aboutYouDialog(page)).toBeVisible();
    await expect(noteField(page)).toHaveValue("Do not lose me");
    await expect(drawer(page)).toBeVisible();

    // The tap left the cursor in the dialog, so Escape still cancels it and
    // never reaches the drawer.
    await expect(noteField(page)).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(aboutYouDialog(page)).toHaveCount(0);
    await expect(drawer(page)).toBeVisible();
  });

  test("typing in the dialog, then resizing across the breakpoint and back, keeps the dialog open with the cursor in it and the text as typed", async ({
    page,
  }) => {
    const typed = "Typed before the rotation";
    await page.goto("/chat");
    await openDrawer(page);
    await openAboutYou(page);
    await noteField(page).click();
    await page.keyboard.type(typed);
    await expect(noteField(page)).toBeFocused();

    await page.setViewportSize(DESKTOP);
    await expect(page.getByRole("complementary")).toBeVisible();
    await expect(aboutYouDialog(page)).toBeVisible();
    await expect(noteField(page)).toBeFocused();
    await expect(noteField(page)).toHaveValue(typed);

    await page.setViewportSize(PHONE);
    await expect(page.getByRole("button", { name: "Open menu" })).toBeVisible();
    await expect(aboutYouDialog(page)).toBeVisible();
    await expect(noteField(page)).toBeFocused();
    await expect(noteField(page)).toHaveValue(typed);

    await page.keyboard.type(" and after");
    await expect(noteField(page)).toHaveValue(`${typed} and after`);
  });
});
