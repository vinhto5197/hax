import { expect, test, type Page } from "@playwright/test";
import { composer, REPLY } from "./chat";

test.use({ viewport: { width: 390, height: 844 } });

// startConversation in chat.ts waits for the sidebar row, which a phone does
// not mount while the drawer is closed.
async function phoneConversation(page: Page, text: string) {
  await composer(page).fill(text);
  await composer(page).press("Enter");
  const main = page.locator("main");
  await expect(main.getByText(REPLY, { exact: true }).last()).toBeVisible();
  await expect(page).toHaveURL(/\/chat\/[^/]+$/);
  return new URL(page.url()).pathname;
}

function menuButton(page: Page) {
  return page.getByRole("button", { name: "Open menu" });
}

function drawer(page: Page) {
  return page.getByRole("dialog", { name: "Menu" });
}

test("at phone width the top bar has the menu, the wordmark and +, and no sidebar", async ({
  page,
}) => {
  await page.goto("/chat");

  await expect(menuButton(page)).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Hax home", exact: true }),
  ).toBeVisible();
  const newChat = page.getByRole("link", { name: "New chat", exact: true });
  await expect(newChat).toBeVisible();
  await expect(page.getByRole("navigation")).toHaveCount(0);
  await expect(page.getByRole("link", { name: "+ New chat" })).toHaveCount(0);
});

test("the drawer takes focus, and Escape closes it and returns focus to the menu button", async ({
  page,
}) => {
  await page.goto("/chat");
  await menuButton(page).click();

  await expect(drawer(page)).toBeVisible();
  await expect(drawer(page)).toBeFocused();
  await expect(drawer(page).getByRole("navigation")).toBeVisible();

  await page.keyboard.press("Escape");
  await expect(drawer(page)).toHaveCount(0);
  await expect(menuButton(page)).toBeFocused();
  await expect(menuButton(page)).toHaveAttribute("aria-expanded", "false");
});

test("while the drawer is open the page behind is inert and the thread does not scroll", async ({
  page,
}) => {
  const lines = Array.from({ length: 60 }, (_, i) => `Drawer line ${i + 1}`);
  await page.goto("/chat");
  await phoneConversation(page, `Drawer journey: tall\n${lines.join("\n")}`);

  // The scroller has no role: the first scrollable element in main.
  const scroller = await page.locator("main").evaluateHandle((main) => {
    const divs = Array.from(main.querySelectorAll("div"));
    return divs.find((el) => getComputedStyle(el).overflowY === "auto")!;
  });
  const before = await scroller.evaluate((el) => el.scrollTop);
  expect(before).toBeGreaterThan(200);

  await menuButton(page).click();
  await expect(drawer(page)).toBeVisible();
  const behind = page.locator("main").locator("..");
  await expect(behind).toHaveAttribute("inert", "");
  const overflow = await page.evaluate(() => document.body.style.overflow);
  expect(overflow).toBe("hidden");

  // Over the backdrop, right of the drawer (at most 85vw wide).
  await page.mouse.move(375, 420);
  await page.mouse.wheel(0, -400);
  await expect(drawer(page)).toBeVisible();
  // Two frames give a wheel scroll time to land before it is read.
  const after = await scroller.evaluate(async (el) => {
    await new Promise((resolve) => {
      requestAnimationFrame(() => requestAnimationFrame(resolve));
    });
    return el.scrollTop;
  });
  expect(after).toBe(before);

  await page.keyboard.press("Escape");
  await expect(behind).not.toHaveAttribute("inert");
});

test("opening a conversation from the drawer closes it", async ({ page }) => {
  await page.goto("/chat");
  const first = await phoneConversation(page, "Drawer journey: first");
  await page.getByRole("link", { name: "New chat", exact: true }).click();
  await expect(page).toHaveURL(/\/chat$/);
  const second = await phoneConversation(page, "Drawer journey: second");
  expect(second).not.toBe(first);

  await menuButton(page).click();
  await drawer(page).locator(`a[href="${first}"]`).click();
  await expect(page).toHaveURL(new RegExp(`${first}$`));
  await expect(drawer(page)).toHaveCount(0);
  const main = page.locator("main");
  await expect(main.getByText("Drawer journey: first")).toBeVisible();
});

test("the open drawer goes away when the window becomes desktop width", async ({
  page,
}) => {
  await page.goto("/chat");
  await menuButton(page).click();
  await expect(drawer(page)).toBeVisible();

  await page.setViewportSize({ width: 1280, height: 800 });
  await expect(drawer(page)).toHaveCount(0);
  await expect(page.getByRole("navigation")).toBeVisible();
  await expect(page.getByRole("link", { name: "+ New chat" })).toBeVisible();
  await expect(menuButton(page)).toBeHidden();
});
